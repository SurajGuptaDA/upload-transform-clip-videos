from __future__ import annotations
import argparse, re, shutil, subprocess, tempfile
from pathlib import Path
import yt_dlp
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parent
TIMESTAMPS = ROOT / "timestamps.txt"
DOWNLOADS = ROOT / "downloads"
CLIPS = ROOT / "pre_processed_clips"
OUTPUT = ROOT / "my_reels"
W, H = 1080, 1920
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
URL_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+", re.I)
RANGE_RE = re.compile(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*[-–—]\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*$")

def ffmpeg_path():
    p = shutil.which("ffmpeg")
    if not p: raise RuntimeError("FFmpeg not found. Run: winget install Gyan.FFmpeg, then reopen the terminal.")
    return p

def to_seconds(s):
    p = [float(x) for x in s.split(":")]
    if len(p) == 2:
        m, sec = p
        if m < 0 or not 0 <= sec < 60: raise ValueError(f"Invalid timestamp: {s}")
        return m * 60 + sec
    if len(p) == 3:
        h, m, sec = p
        if h < 0 or not 0 <= m < 60 or not 0 <= sec < 60: raise ValueError(f"Invalid timestamp: {s}")
        return h * 3600 + m * 60 + sec
    raise ValueError(f"Invalid timestamp: {s}")

def safe_name(s):
    return re.sub(r"\s+", " ", re.sub(r'[<>:"/\\|?*]', "_", s)).strip()[:80] or "video"

def parse_jobs():
    if not TIMESTAMPS.exists(): raise FileNotFoundError("timestamps.txt is missing.")
    jobs, current = [], None
    for n, raw in enumerate(TIMESTAMPS.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"): continue
        u = URL_RE.search(line)
        if u:
            if current and current["ranges"]: jobs.append(current)
            current = {"url": u.group(0).rstrip(".,)"), "ranges": []}
            continue
        r = RANGE_RE.match(line)
        if r:
            if current is None: raise ValueError(f"Timestamp without URL at line {n}")
            start, end = map(to_seconds, r.groups())
            if end <= start: raise ValueError(f"End must exceed start at line {n}")
            current["ranges"].append((start, end))
            continue
        raise ValueError(f"Invalid line {n}: {line}")
    if current and current["ranges"]: jobs.append(current)
    if not jobs: raise ValueError("No valid URL/timestamp jobs found in timestamps.txt")
    return jobs

def run(cmd, cwd=None):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd)
    if p.returncode: raise RuntimeError(p.stdout[-6000:])

def download(url, index):
    DOWNLOADS.mkdir(exist_ok=True)
    opts = {"format":"bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
            "outtmpl":str(DOWNLOADS / f"source_{index}.%(ext)s"),
            "merge_output_format":"mp4", "noplaylist":True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        prepared = Path(ydl.prepare_filename(info))
    for p in (prepared.with_suffix(".mp4"), prepared):
        if p.exists(): return p, info
    raise RuntimeError("Downloaded source file not found.")

# def cut_clip(ffmpeg, source, dest, start, end):
#     run([ffmpeg,"-hide_banner","-y","-ss",str(start),"-i",str(source),"-t",str(end-start),
#          "-map","0:v:0","-map","0:a?","-c:v","libx264","-preset","veryfast","-crf","18",
#          "-c:a","aac","-b:a","192k","-movflags","+faststart",str(dest)])
#     if not dest.exists() or not dest.stat().st_size: raise RuntimeError("Clip export failed.")

def ass_time(t):
    cs = max(0, round(t * 100)); h, rem = divmod(cs, 360000); m, rem = divmod(rem, 6000); s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"

def ass_escape(s):
    return s.replace("\\\\", r"\\\\").replace("{", r"\\{").replace("}", r"\\}").replace("\\n", " ")

def group_words(words, limit=4):
    groups, current, start = [], [], None
    for word in words:
        token = word["text"].strip()
        if not token: continue
        if current and (len(current) >= limit or word["end"] - start > 3 or word["start"] - current[-1]["end"] > .8):
            groups.append(current); current, start = [], None
        if not current: start = word["start"]
        current.append(word)
        if token.endswith((".", "!", "?", ",", ";", ":")):
            groups.append(current); current, start = [], None
    if current: groups.append(current)
    return groups

def write_ass(words, path):
    header = f"""[Script Info]
Title: Automated Shorts Captions
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,82,&H00FFFFFF,&H0000D7FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,70,70,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for group in group_words(words):
        start, end = max(0, group[0]["start"]-.04), max(group[0]["start"]+.12, group[-1]["end"]+.12)
        # parts = [r"{\\kf" + str(max(1, round((w["end"]-w["start"])*100))) + "}" + ass_escape(w["text"].strip()) for w in group]
        parts = [r"{\kf" + str(max(1, round((w["end"]-w["start"])*100))) + "}" + ass_escape(w["text"].strip()) for w in group]
        # lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{' '.join(parts)}\\n")
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{' '.join(parts)}\n")
    path.write_text("".join(lines), encoding="utf-8-sig")

def escape_filter_path(path):
    s = path.resolve().as_posix().replace("\\\\","\\\\\\\\").replace(":","\\\\:")
    return s.replace("'","\\\\'").replace(",","\\\\,").replace("[","\\\\[").replace("]","\\\\]")

def make_reel(ffmpeg, source, dest, start, end, model, language, crf, preset):
    print(f"Transcribing: {source.name}")
    segments, _ = model.transcribe(str(source), language=language, word_timestamps=True, vad_filter=True, beam_size=5, clip_timestamps=f"{start},{end}")
    words = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                if w.word.strip(): words.append({"start": float(w.start) - start, "end": float(w.end) - start, "text": w.word.strip()})
        else:
            tokens = seg.text.strip().split()
            if tokens:
                d = max(.01, seg.end-seg.start)/len(tokens)
                words.extend({"start": seg.start + i*d - start, "end": seg.start + (i+1)*d - start, "text": t} for i, t in enumerate(tokens))
    if not words: raise RuntimeError("No speech detected; this workflow does not export silent/no-speech clips.")
    with tempfile.TemporaryDirectory(prefix="reel_subs_") as td:
        ass = Path(td)/"captions.ass"; write_ass(words, ass)
        # print("\nGenerated ASS subtitle file:")
        # print(ass.read_text(encoding="utf-8-sig")[:2000])
        # input("Press Enter to continue...")
        # vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,subtitles=filename='{escape_filter_path(ass)}'"
        # vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,subtitles=captions.ass"
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,"
            f"subtitles=filename=captions.ass"
        )
        run([ffmpeg,"-hide_banner","-y","-ss", str(start),"-i", str(source),
             "-t", str(end - start),"-map","0:v:0","-map","0:a?","-vf",vf,
             "-c:v","libx264","-preset",preset,"-crf",str(crf),"-pix_fmt","yuv420p",
             "-c:a","aac","-b:a","192k","-movflags","+faststart","-shortest",str(dest)], cwd=td)
    if not dest.exists() or not dest.stat().st_size: raise RuntimeError("Reel export failed.")

def extract_clips(ffmpeg, model, language, crf, preset):
    jobs = parse_jobs()
    DOWNLOADS.mkdir(exist_ok=True); OUTPUT.mkdir(exist_ok=True)
    made = []
    errors = []
    for vi, job in enumerate(jobs, 1):
        print(f"\\nDownloading source {vi}/{len(jobs)}...")
        source, info = download(job["url"], vi)
        title = safe_name(info.get("title", "video"))
        for ci, (start, end) in enumerate(job["ranges"], 1):
            if info.get("duration") and end > info["duration"]:
                print(f"Skipping clip {ci}: end timestamp exceeds source duration."); continue
            dest = OUTPUT / f"{title}_clip_{ci:02d}.mp4"
            print(f"Cutting {title}: {start:.2f}s to {end:.2f}s")
            try:
                make_reel(ffmpeg, source, dest, start, end, model, language, crf, preset)
                made.append(dest); print(f"Created: {dest.name}")
            except Exception as e:
                errors.append((dest.name, str(e))); print(f"FAILED: {e}")
    return made, errors


def main():
    ap = argparse.ArgumentParser(description="YouTube timestamps -> landscape clips -> vertical captioned Reels")
    ap.add_argument("--model", default="base", choices=["tiny","base","small","medium","large-v3"])
    ap.add_argument("--device", default="cpu", choices=["cpu","cuda"])
    ap.add_argument("--compute-type", default=None)
    ap.add_argument("--language", default=None, help="e.g. en; auto-detect if omitted")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--preset", default="medium", choices=["ultrafast","fast","medium","slow"])
    a = ap.parse_args()
    try:
        ffmpeg = ffmpeg_path()
        ctype = a.compute_type or ("float16" if a.device == "cuda" else "int8")
        model = WhisperModel(a.model, device=a.device, compute_type=ctype)
        print(f"Loading Whisper {a.model} ({a.device}/{ctype})...")
        OUTPUT.mkdir(exist_ok=True)
        clips, errors = extract_clips(ffmpeg, model, a.language, a.crf, a.preset)
        print(f"\nFinished. Successful: {len(clips)}. Failed: {len(errors)}. Output: {OUTPUT}")
    except Exception as e:
        print(f"\\nERROR: {e}"); return 1

if __name__ == "__main__":
    raise SystemExit(main())
    