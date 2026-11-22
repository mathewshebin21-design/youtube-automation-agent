"""Review-only Twitch VOD Shorts candidate generator; no YouTube publishing."""
import argparse
import json
import pathlib
import re
import subprocess
import cv2
import numpy as np

def run(args):
    subprocess.run(args, check=True)

def inspect(video, interval=2):
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    samples = []
    last = None
    for t in np.arange(0, duration, interval):
        cap.set(cv2.CAP_PROP_POS_MSEC, float(t) * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(cv2.resize(frame, (256, 144)), cv2.COLOR_BGR2GRAY)
        motion = float(np.mean(cv2.absdiff(gray, last))) if last is not None else 0.0
        samples.append((float(t), motion))
        last = gray
    cap.release()
    return duration, samples

def candidates(samples, duration, seconds=35, limit=6):
    ranked = []
    for start in np.arange(0, max(1, duration - seconds), max(8, seconds // 2)):
        window = [motion for t, motion in samples if start <= t < start + seconds]
        if window:
            ranked.append((float(np.percentile(window, 75)), float(start), float(min(duration, start + seconds))))
    ranked.sort(reverse=True)
    selected = []
    for score, start, end in ranked:
        if all(end <= a or start >= b for _, a, b in selected):
            selected.append((score, start, end))
        if len(selected) == limit:
            break
    return selected

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://www.twitch.tv/videos/2936544559")
    parser.add_argument("--input")
    parser.add_argument("--output", default="output")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--render", action="store_true")
    args = parser.parse_args()
    out = pathlib.Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if args.input:
        video = pathlib.Path(args.input)
    else:
        if not re.fullmatch(r"https://(?:www\.)?twitch\.tv/videos/\d+", args.url):
            raise ValueError("Only Twitch VOD URLs are accepted")
        run(["yt-dlp", "--no-playlist", "--merge-output-format", "mp4", "-o", str(out / "vod.%(ext)s"), args.url])
        videos = [p for p in out.glob("vod.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
        if not videos:
            raise FileNotFoundError("No playable VOD downloaded")
        video = videos[0]
    if not video.exists():
        raise FileNotFoundError(video)
    duration, samples = inspect(video)
    selected = candidates(samples, duration, limit=args.limit)
    manifest = {"source": args.url if not args.input else str(video), "duration_seconds": duration, "selection_method": "motion heuristic, NOT gameplay understanding", "publishing_allowed": False, "clips": []}
    for index, (score, start, end) in enumerate(selected, 1):
        name = f"short_{index:02d}.mp4"
        manifest["clips"].append({"file": name, "start": round(start, 2), "end": round(end, 2), "motion_score": round(score, 2), "review_status": "pending"})
        if args.render:
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(video), "-t", str(end-start), "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(out / name)])
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"candidates": len(selected), "rendered": args.render, "manifest": str(out / "manifest.json")}))

if __name__ == "__main__":
    main()
