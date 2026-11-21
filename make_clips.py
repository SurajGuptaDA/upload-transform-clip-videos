
#!/usr/bin/env python3

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
import yt_dlp

ROOT = Path(__file__).resolve().parent
INPUT_FILE = ROOT / "timestamps.txt"
DOWNLOAD_DIR = ROOT / "downloads"
OUTPUT_DIR = ROOT / "pre_processed_clips"

MAX_HEIGHT = 1080

URL_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+",
    re.I
)

RANGE_RE = re.compile(
    r"^\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)"
    r"\s*[-–—]\s*"
    r"(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)\s*$"
)


def timestamp_to_seconds(value):
    parts = [float(x) for x in value.split(":")]

    if len(parts) == 2:
        minutes, seconds = parts
        if minutes < 0 or not 0 <= seconds < 60:
            raise ValueError(f"Invalid timestamp: {value}")
        return minutes * 60 + seconds

    if len(parts) == 3:
        hours, minutes, seconds = parts
        if hours < 0 or not 0 <= minutes < 60 or not 0 <= seconds < 60:
            raise ValueError(f"Invalid timestamp: {value}")
        return hours * 3600 + minutes * 60 + seconds

    raise ValueError(f"Invalid timestamp: {value}")


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return re.sub(r"\s+", " ", name).strip()[:80]


def parse_input():
    jobs = []
    current = None

    with open(INPUT_FILE, "r", encoding="utf-8-sig") as file:
        for line_number, raw in enumerate(file, 1):
            line = raw.strip()

            if not line or line.startswith("#"):
                continue

            url_match = URL_RE.search(line)

            if url_match:
                if current and current["clips"]:
                    jobs.append(current)

                current = {
                    "url": url_match.group(0).rstrip(".,)"),
                    "clips": []
                }
                continue

            range_match = RANGE_RE.match(line)

            if range_match:
                if current is None:
                    raise ValueError(
                        f"Timestamp without URL at line {line_number}"
                    )

                start = timestamp_to_seconds(range_match.group(1))
                end = timestamp_to_seconds(range_match.group(2))

                if end <= start:
                    raise ValueError("End time must exceed start time.")

                current["clips"].append((start, end))
                continue

            raise ValueError(f"Invalid input at line {line_number}: {line}")

    if current and current["clips"]:
        jobs.append(current)

    if not jobs:
        raise ValueError("No valid video jobs found.")

    return jobs


def download_video(url, index):
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    options = {
        "format": (
            "bestvideo[height<=1080]+bestaudio/"
            "best[height<=1080]/best"
        ),
        "outtmpl": str(
            DOWNLOAD_DIR / f"source_{index}.%(ext)s"
        ),
        "merge_output_format": "mp4",
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
        prepared = Path(ydl.prepare_filename(info))

        candidates = [
            prepared.with_suffix(".mp4"),
            prepared
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate, info

        raise RuntimeError("Downloaded source file not found.")


def make_clip(ffmpeg, source, destination, start, end):
    command = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-i", str(source),
        "-ss", str(start),
        "-t", str(end - start),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(destination)
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:])

    if not destination.exists() or destination.stat().st_size == 0:
        raise RuntimeError("Clip was not created successfully.")


def main():
    ffmpeg = shutil.which("ffmpeg")

    if not ffmpeg:
        raise RuntimeError("FFmpeg is not installed or not in PATH.")

    jobs = parse_input()

    OUTPUT_DIR.mkdir(exist_ok=True)
    DOWNLOAD_DIR.mkdir(exist_ok=True)

    clips_created = []

    for video_index, job in enumerate(jobs, 1):
        print(f"\nDownloading video {video_index}...")

        source, info = download_video(
            job["url"],
            video_index
        )

        title = safe_name(info.get("title", "video"))

        for clip_index, (start, end) in enumerate(
            job["clips"], 1
        ):
            if info.get("duration") and end > info["duration"]:
                print(f"Skipping clip {clip_index}: exceeds video duration.")
                continue

            filename = (
                f"{title}_clip_{clip_index:02d}.mp4"
            )

            destination = OUTPUT_DIR / filename

            print(
                f"Creating clip {clip_index}: "
                f"{start}s - {end}s"
            )

            make_clip(
                ffmpeg,
                source,
                destination,
                start,
                end
            )

            clips_created.append(destination)

            print(f"Created: {filename}")

    if clips_created:
        # zip_path = OUTPUT_DIR / "all_clips.zip"

        # with zipfile.ZipFile(
        #     zip_path,
        #     "w",
        #     zipfile.ZIP_DEFLATED
        # ) as archive:

        #     for clip in clips_created:
        #         archive.write(clip, arcname=clip.name)

        print(f"\nSuccessfully created {len(clips_created)} clips.")
        # print(f"ZIP saved at: {zip_path}")

    else:
        print("\nNo clips were created.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nERROR: {error}")

    input("\nPress Enter to exit...")
