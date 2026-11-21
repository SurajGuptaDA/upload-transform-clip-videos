from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

from faster_whisper import WhisperModel

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
WIDTH, HEIGHT = 1080, 1920


def run_command(command: list[str]) -> None:
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stdout[-7000:])


def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if not path:
        raise RuntimeError(
            "FFmpeg was not found. Install it with: winget install Gyan.FFmpeg\n"
            "Then close and reopen Command Prompt and run this script again."
        )
    return path


def escape_filter_path(path: Path) -> str:
    # Escape a path for FFmpeg's filtergraph parser (not the Windows shell).
    value = path.resolve().as_posix()
    value = value.replace("\\", "\\\\")
    value = value.replace(":", r"\:")
    value = value.replace("'", r"\'")
    value = value.replace(",", r"\,")
    value = value.replace("[", r"\[").replace("]", r"\]")
    return value


def seconds_to_ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, rem = divmod(centiseconds, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", " ")


def group_words(words: list[dict], max_words: int = 4, max_duration: float = 3.0) -> list[list[dict]]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    start = None
    for word in words:
        token = word["text"].strip()
        if not token:
            continue
        if current and (
            len(current) >= max_words
            or word["end"] - (start if start is not None else word["start"]) > max_duration
            or word["start"] - current[-1]["end"] > 0.8
        ):
            groups.append(current)
            current = []
            start = None
        if not current:
            start = word["start"]
        current.append(word)
        # Natural sentence boundaries make captions easier to read.
        if token.endswith((".", "!", "?", ",", ";", ":")):
            groups.append(current)
            current = []
            start = None
    if current:
        groups.append(current)
    return groups


def write_karaoke_ass(words: list[dict], ass_path: Path, font: str = "Arial") -> None:
    groups = group_words(words)
    header = f"""[Script Info]
Title: Automated Shorts Captions
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},82,&H00FFFFFF,&H0000D7FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,70,70,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for group in groups:
        start = max(0.0, group[0]["start"] - 0.04)
        end = max(start + 0.12, group[-1]["end"] + 0.12)
        parts = []
        for item in group:
            duration = max(1, round((item["end"] - item["start"]) * 100))
            parts.append(r"{\kf" + str(duration) + "}" + ass_escape(item["text"].strip()))
        caption = " ".join(parts)
        lines.append(
            f"Dialogue: 0,{seconds_to_ass_time(start)},{seconds_to_ass_time(end)},"
            f"Default,,0,0,0,,{caption}\n"
        )
    ass_path.write_text("".join(lines), encoding="utf-8-sig")


def transcribe(video: Path, model: WhisperModel, language: str | None) -> list[dict]:
    print(f"Transcribing: {video.name}")
    segments, info = model.transcribe(
        str(video),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    words: list[dict] = []
    for segment in segments:
        if segment.words:
            for word in segment.words:
                token = word.word.strip()
                if token:
                    words.append({
                        "start": float(word.start),
                        "end": float(word.end),
                        "text": token,
                    })
        else:
            # Fallback for an unusual segment without word-level alignment.
            tokens = segment.text.strip().split()
            if tokens:
                duration = max(0.01, segment.end - segment.start) / len(tokens)
                for i, token in enumerate(tokens):
                    words.append({
                        "start": segment.start + i * duration,
                        "end": segment.start + (i + 1) * duration,
                        "text": token,
                    })
    return words


def process_video(
    source: Path,
    output_dir: Path,
    ffmpeg: str,
    model: WhisperModel,
    language: str | None,
    crf: int,
    preset: str,
    keep_temp: bool,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{source.stem}_short.mp4"
    print(f"\n[1/3] Transcribing: {source.name}")
    words = transcribe(source, model, language)
    if not words:
        raise RuntimeError("No speech was detected. This project currently exports captioned videos only.")

    with tempfile.TemporaryDirectory(prefix="shorts_") as temp_name:
        ass_path = Path(temp_name) / "captions.ass"
        write_karaoke_ass(words, ass_path)
        print(f"[2/3] Creating vertical crop and word-synced captions ({len(words)} words)")
        subtitle_filter_path = escape_filter_path(ass_path)
        video_filter = (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,"
            f"subtitles=filename='{subtitle_filter_path}'"
        )
        command = [
            ffmpeg, "-hide_banner", "-y", "-i", str(source),
            "-map", "0:v:0", "-map", "0:a?",
            "-vf", video_filter,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest", str(destination),
        ]
        run_command(command)

    print(f"[3/3] Done: {destination}")


def get_inputs(input_path: Path) -> list[Path]:
    if input_path.is_file():
        if input_path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise RuntimeError(f"Unsupported video format: {input_path.suffix}")
        return [input_path]
    if input_path.is_dir():
        return sorted(p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
    raise RuntimeError(f"Input path does not exist: {input_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch convert landscape videos to 9:16 Shorts/Reels with local word-synced captions."
    )
    parser.add_argument("--input", default="pre_processed_clips", help="Video file or folder (default: input)")
    parser.add_argument("--output", default="my_reels", help="Output folder (default: output)")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Whisper model size; larger is more accurate but slower (default: base)")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="Inference device (default: cpu)")
    parser.add_argument("--compute-type", default=None, help="e.g. int8 for CPU, float16 for CUDA")
    parser.add_argument("--language", default=None, help="Spoken language code, e.g. en; auto-detect if omitted")
    parser.add_argument("--crf", type=int, default=20, help="Video quality: lower is higher quality (default: 20)")
    parser.add_argument("--preset", default="medium", choices=["ultrafast", "fast", "medium", "slow"],
                        help="FFmpeg encoding speed (default: medium)")
    parser.add_argument("--keep-temp", action="store_true", help="Reserved for future debugging; temp files are still cleaned up")
    args = parser.parse_args()

    try:
        ffmpeg = find_ffmpeg()
        inputs = get_inputs(Path(args.input))
        if not inputs:
            print(f"No supported videos found in: {args.input}")
            return 0

        compute_type = args.compute_type or ("float16" if args.device == "cuda" else "int8")
        print(f"Loading Whisper '{args.model}' model on {args.device} ({compute_type}).")
        print("The first run downloads the model once; later runs use the local cached copy.")
        model = WhisperModel(args.model, device=args.device, compute_type=compute_type)

        output_dir = Path(args.output)
        failures = []
        for index, source in enumerate(inputs, 1):
            print(f"\n========== Video {index}/{len(inputs)} ==========")
            try:
                process_video(source, output_dir, ffmpeg, model, args.language, args.crf, args.preset, args.keep_temp)
            except Exception as exc:
                failures.append((source.name, str(exc)))
                print(f"ERROR processing {source.name}: {exc}")

        print("\nBatch complete.")
        if failures:
            print("Failed files:")
            for name, reason in failures:
                print(f" - {name}: {reason}")
            return 1
        return 0
    except Exception as exc:
        print(f"\nFATAL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
