"""Review-only Twitch VOD Shorts candidate generator; no YouTube publishing."""
import argparse
import json
import pathlib
import re
import subprocess
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import compliance  # noqa: E402
import render  # noqa: E402
import signals  # noqa: E402

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
    """PR #1 motion-only ranking, kept for comparison/backwards compatibility."""
    rows = signals.score_windows(duration, samples, seconds=seconds, weights={"motion": 1.0})
    return [(r["raw"]["motion_p75"], r["start"], r["end"]) for r in signals.select(rows, limit)]

def fetch_info(url):
    """yt-dlp metadata only (no download); used to prove the VOD owner before anything is fetched."""
    p = subprocess.run(["yt-dlp", "-J", "--no-playlist", "--", url], capture_output=True, text=True)
    if p.returncode != 0:
        raise PermissionError("could not read VOD metadata (owner unknown); refusing to continue")
    return json.loads(p.stdout)


def source_owner(info):
    vid = str((info or {}).get("id") or "")
    if vid.startswith("v") and vid[1:].isdigit():
        vid = vid[1:]
    return {"vod_id": vid if vid.isdigit() else "", "uploader": info.get("uploader"), "uploader_id": info.get("uploader_id"),
            "channel": info.get("channel"), "channel_id": info.get("channel_id"), "tool": "yt-dlp -J"} if info else {}


def layout_profile(name):
    pol = json.loads((pathlib.Path(__file__).parent / "editorial-policy.json").read_text())
    profiles = pol.get("layout_profiles", {})
    if name is None:
        return profiles.get(pol.get("default_layout_profile", ""), {})
    if name not in profiles:
        raise ValueError(f"unknown layout profile {name!r}; define it under layout_profiles in editorial-policy.json")
    return profiles[name]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="YOUR OWN Twitch VOD URL (no default; own VODs only)")
    parser.add_argument("--input")
    parser.add_argument("--output", default="output")
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--seconds", type=int, default=35, help="window length (15-60)")
    parser.add_argument("--chat", help="chat export JSON (TwitchDownloader or list of offsets)")
    parser.add_argument("--transcript", help="transcript JSON with segments [{start,end,text}]")
    parser.add_argument("--no-audio-signal", action="store_true")
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--layout", choices=render.LAYOUTS, default="blur")
    parser.add_argument("--crop-x", default="0.5", help="0..1 or 'smart'")
    parser.add_argument("--facecam-box", help="x,y,w,h fractions of the source frame, for --layout split")
    parser.add_argument("--captions", action="store_true", help="burn in faster-whisper captions if installed")
    parser.add_argument("--info-json", help="yt-dlp .info.json for --input files (owner check needs it)")
    parser.add_argument("--profile", default=None, help="stream-layout profile name from editorial-policy.json")
    args = parser.parse_args()
    if not 15 <= args.seconds <= 60:
        raise ValueError("--seconds must be 15-60")
    facecam = render.parse_box(args.facecam_box) if args.facecam_box else None
    if not args.input and not args.url:
        parser.error("--url (your own Twitch VOD) or --input is required; there is no default source")
    crop_x = "smart" if args.crop_x == "smart" else float(args.crop_x)
    out = pathlib.Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    if args.input:
        video = pathlib.Path(args.input)
        info = json.loads(pathlib.Path(args.info_json).read_text()) if args.info_json else {}
    else:
        if not re.fullmatch(r"https://(?:www\.)?twitch\.tv/videos/\d+", args.url or ""):
            raise ValueError("Only Twitch VOD URLs are accepted")
        if any(out.glob("vod.*")):
            raise FileExistsError(f"{out} already holds a VOD; use a fresh --output so clips never mix sources")
        info = fetch_info(args.url)
        status, why = compliance.owner_match(source_owner(info))
        if status != compliance.PASS:
            raise PermissionError("refusing to download: " + why)
        (out / "vod.info.json").write_text(json.dumps(source_owner(info), indent=2))
        run(["yt-dlp", "--no-playlist", "--merge-output-format", "mp4", "-o", str(out / "vod.%(ext)s"), "--", args.url])
        videos = [p for p in out.glob("vod.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
        if not videos:
            raise FileNotFoundError("No playable VOD downloaded")
        video = videos[0]
    owner = source_owner(info)
    profile = layout_profile(args.profile)
    if profile.get("facecam_box") and not facecam:
        facecam = render.parse_box(",".join(str(x) for x in profile["facecam_box"]))
    if args.layout == "split" and not facecam:
        raise ValueError("--layout split needs --facecam-box or a profile with facecam_box")
    if not video.exists():
        raise FileNotFoundError(video)
    duration, samples = inspect(video)
    audio = [] if args.no_audio_signal else signals.audio_loudness(video)
    chat = signals.chat_times(args.chat) if args.chat else None
    transcript = signals.transcript_segments(args.transcript) if args.transcript else None
    rows = signals.score_windows(duration, samples, audio=audio, chat=chat, transcript=transcript, seconds=args.seconds)
    selected = signals.select(rows, limit=args.limit, min_score=args.min_score)
    source_url = args.url if not args.input else (f"https://www.twitch.tv/videos/{owner['vod_id']}" if owner.get("vod_id") else None)
    manifest = {"schema": "cutscenecity.review-manifest/2", "source": source_url or str(video), "duration_seconds": duration,
                "selection_method": "weighted percentile ranks of " + ", ".join(selected[0]["signals_used"] if selected else ["motion"])
                + " - heuristic, NOT gameplay understanding",
                "publishing_allowed": False, "clips": []}
    for index, row in enumerate(selected, 1):
        name = f"short_{index:02d}.mp4"
        clip = {"file": name, "start": row["start"], "end": row["end"], "motion_score": round(row["raw"]["motion_p75"], 2),
                "combined_score": row["combined_score"], "signals": row["raw"], "signal_ranks": row["signal_ranks"],
                "selection_note": row["selection_note"], "review_status": "pending",
                "provenance": {"source_platform": "twitch", "source_url": source_url or "",
                               "source_channel_name": owner.get("uploader") or owner.get("uploader_id") or "",
                               "source_channel_id": owner.get("uploader_id") or owner.get("channel_id") or "",
                               "source_owner": owner},
                "metadata": {"title": "", "description": "", "tags": [], "privacyStatus": "private", "containsSyntheticMedia": None},
                "transformation_note": ""}
        compliance.init_clip(clip)
        if args.render:
            clip["render"] = render.render(video, row["start"], row["end"], out, name, captions=args.captions,
                                           layout=args.layout, crop_x=crop_x, facecam=facecam,
                                           blur_regions=profile.get("blur_regions", []))
            clip["render"]["facecam"] = facecam
            clip["render"]["profile"] = args.profile
        compliance.evaluate(clip, {})
        manifest["clips"].append(clip)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"candidates": len(selected), "rendered": args.render, "manifest": str(out / "manifest.json")}))

if __name__ == "__main__":
    main()
