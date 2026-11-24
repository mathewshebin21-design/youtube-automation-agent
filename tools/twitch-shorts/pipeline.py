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
import qa  # noqa: E402
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


def manual_windows(specs, duration):
    rows = []
    for spec in specs:
        s, e = (float(x) for x in str(spec).split("-", 1))
        if not (0 <= s < e <= duration + 0.01 and 15 <= e - s <= 60):
            raise ValueError(f"--window {spec}: must be inside the input and 15-60 s long")
        rows.append({"start": s, "end": e, "raw": {"motion_p75": 0.0}, "combined_score": None, "signal_ranks": {},
                     "signals_used": ["manual window"],
                     "selection_note": f"Manual window {s:g}-{e:g}s. A human must confirm setup, payoff and that this is not a story cutscene."})
    return rows


def join_adjacent(rows, max_len=60.0):
    """Merge picks that touch end-to-start into one clip (<= max_len s); records the join offset (flash_cut effect)."""
    out = []
    for r in sorted(rows, key=lambda r: r["start"]):
        prev = out[-1] if out else None
        if prev and abs(prev["end"] - r["start"]) < 0.01 and r["end"] - prev["start"] <= max_len:
            prev["joins"] = prev.get("joins", []) + [prev["end"] - prev["start"]]
            prev["end"] = r["end"]
            prev["selection_note"] += " Joined with the adjacent pick: " + r["selection_note"]
        else:
            out.append(dict(r))
    return out


def pre_edit_refusal(args):
    """Phase 2.7: pipeline.py renders the PRE-EDIT clip only. Captions need a mic stem (a Twitch VOD has one mixed
    track) and the edit style/effects are a per-clip human choice recorded later with review.py edit."""
    if args.captions:
        return ("--captions refused: captions come only from a separate creator mic stem, never the mixed VOD track. "
                "Use review.py commentary --mic/--mic-stream, then review.py edit --effects captions")
    if (args.edit_style or "off") not in ("off", "none") or args.caption_style or args.flash_cut:
        return ("edit style/effects are chosen per clip by a human after review: review.py edit --clip short_NN.mp4 "
                "--style clean|hype --effects ... --by NAME (pipeline.py renders the pre-edit clip only)")
    return None


def credit_line(owner, vod_url):
    """Factual attribution default from yt-dlp info.json fields only (no promo copy)."""
    login = (owner.get("uploader_id") or "").strip()
    if not login or not vod_url:
        return ""
    return f"From my Twitch stream: https://www.twitch.tv/{login} \u2014 full VOD: {vod_url}"


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
    parser.add_argument("--captions", action="store_true", help=argparse.SUPPRESS)  # refused since phase 2.7 (mixed track)
    parser.add_argument("--info-json", help="yt-dlp .info.json for --input files (owner check needs it)")
    parser.add_argument("--upscale", default=None, help="2160 (default) | 1440 | off; env CUTSCENECITY_UPSCALE")
    parser.add_argument("--profile", default=None, help="stream-layout profile name from editorial-policy.json")
    parser.add_argument("--edit-style", default=None, choices=("off", "none", "clean", "hype"),
                        help="only off/none here (default): edits are a per-clip human choice made after review (review.py edit)")
    parser.add_argument("--caption-style", default=None, help=argparse.SUPPRESS)  # moved to review.py edit
    parser.add_argument("--window", action="append", default=[], metavar="START-END",
                        help="render this exact window (seconds in the input file) instead of auto-selection; repeatable")
    parser.add_argument("--join-adjacent", action="store_true", help="join two adjacent picks into one clip (<= 60 s total)")
    parser.add_argument("--flash-cut", action="store_true", help=argparse.SUPPRESS)  # moved to review.py edit --effects flash_cut
    args = parser.parse_args()
    refuse = pre_edit_refusal(args)
    if refuse:
        parser.error(refuse)
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
    selected = manual_windows(args.window, duration) if args.window else signals.select(rows, limit=args.limit, min_score=args.min_score)
    if args.join_adjacent:
        selected = join_adjacent(selected)
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
                "metadata": {"title": "", "description": credit_line(owner, source_url), "tags": [], "privacyStatus": "private",
                             "containsSyntheticMedia": None},
                "commentary": {"mic_source": None, "tts_used": False, "commentary_source": None},
                "paid_promotion_suggestion": "none",
                "joins": row.get("joins", []),
                "transformation_note": ""}
        compliance.init_clip(clip)
        if args.render:
            clip["render"] = render.render(video, row["start"], row["end"], out, name,
                                           layout=args.layout, crop_x=crop_x, facecam=facecam,
                                           blur_regions=profile.get("blur_regions", []), upscale=args.upscale,
                                           edit_style="off")   # pre-edit; edits: review.py edit (per-clip human choice)
            clip["render"]["facecam"] = facecam
            clip["render"]["profile"] = args.profile
            clip["technical_qa"] = qa.validate(out / name, row["start"], row["end"])
            clip["commentary"]["mixed_track_speech_share"] = compliance.mixed_speech_share(out / name)
        compliance.evaluate(clip, {})
        manifest["clips"].append(clip)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"candidates": len(selected), "rendered": args.render, "manifest": str(out / "manifest.json")}))

if __name__ == "__main__":
    main()
