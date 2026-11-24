"""Builds a real signed CutsceneCity package with the Python review CLI (no ffmpeg, dummy media).

usage: python make_cutscenecity_package.py <workdir> [--tts] [--synthetic] [--title T] [--start S]
       [--uploader-id LOGIN] [--voice PRESET] [--script-variant N] [--script-file F]
Env: CUTSCENECITY_REVIEW_KEY, CUTSCENECITY_OWNER_TWITCH_LOGIN and CUTSCENECITY_STATE_DIR are set by the caller.
"""
import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2] / "tools" / "twitch-shorts"
sys.path.insert(0, str(ROOT))
import compliance  # noqa: E402
import edit_gates  # noqa: E402
import gatelog  # noqa: E402
import review  # noqa: E402

VOCAB = ("chase alley rooftop sirens bridge harbor neon garage motorbike detour crowd tunnel rain sunset "
         "helicopter dock traffic jump crash escape plan bluff timing nerves luck pier freeway mall swamp").split()


def script_for(n):
    """Deterministic, mutually distinct ~40-word scripts (distinct opener/CTA per variant)."""
    words = [VOCAB[(n * 7 + i * (n + 3)) % len(VOCAB)] + str(n) for i in range(36)]
    v = lambda k: VOCAB[(n + k) % len(VOCAB)]  # noqa: E731
    return (f"{v(0)} {v(5)} take {n}, here goes. " + " ".join(words) +
            f". Variant {n} {v(9)} {v(11)} signing off.")


p = argparse.ArgumentParser()
p.add_argument("workdir")
p.add_argument("--tts", action="store_true")
p.add_argument("--synthetic", action="store_true")
p.add_argument("--title", default="This getaway went sideways fast")
p.add_argument("--start", type=float, default=0.0)
p.add_argument("--uploader-id", default="cutscenecity")
p.add_argument("--voice", default="charon-relaxed")
p.add_argument("--script-variant", type=int, default=0)
p.add_argument("--script-file")
p.add_argument("--paid", default="none", help="none | present | skip")
p.add_argument("--upscale", default=None, help="record render.upscale/output_resolution (e.g. 2160)")
p.add_argument("--mixed", action="store_true", help="single mixed VOD track (no mic stem): mixed-track signed path")
p.add_argument("--mixed-note", default="my live commentary is clearly audible throughout")
p.add_argument("--overlay-flagged", choices=["no", "yes", "unknown"], default="no")
p.add_argument("--overlay-note", default="watched the whole clip, gameplay only")
p.add_argument("--edit", choices=["off", "clean", "hype"], default="off", help="phase 2.7: render edit style (recorded human choice)")
p.add_argument("--effects", default=None, help="comma list for --edit (default: captions for clean, punch_in,end_fade for hype)")
p.add_argument("--no-edit-choice", action="store_true", help="simulate an edit applied without a signed human choice")
p.add_argument("--captions", default=None, help="caption text (one word per 0.5 s from 12 s) -> burned word captions + words.json")
p.add_argument("--caption-start", type=float, default=12.0)
p.add_argument("--raw-profanity", action="store_true", help="do not mask profanity (simulates a bypass)")
p.add_argument("--caption-note", default="read every caption word against the video")
p.add_argument("--skip-caption-review", action="store_true")
p.add_argument("--flash-cuts", type=int, default=0)
p.add_argument("--flash-intensity", type=float, default=0.5)
a = p.parse_args()
work = pathlib.Path(a.workdir)
out = work / "output"
out.mkdir(parents=True, exist_ok=True)
(out / "short_01.mp4").write_bytes(os.urandom(4096))
url = "https://www.twitch.tv/videos/1234567890"
clip = {"file": "short_01.mp4", "start": a.start, "end": a.start + 20.0,
        "provenance": {"source_platform": "twitch", "source_url": url, "source_channel_name": "CutsceneCity",
                       "source_channel_id": a.uploader_id,
                       "source_owner": {"vod_id": "1234567890", "uploader": "CutsceneCity", "uploader_id": a.uploader_id,
                                        "channel": None, "channel_id": None, "tool": "yt-dlp -J"}},
        "metadata": {"title": a.title, "description": f"My take on the chase. Clip from CutsceneCity: {url}",
                     "tags": ["gta", "shorts"], "privacyStatus": "private", "containsSyntheticMedia": bool(a.synthetic)},
        "transformation_note": " ".join(["context"] * 30),
        "commentary": {"path": "/tmp/voice.wav" if a.tts else None, "mic_source": "stream:1",
                       "speech_seconds_live": 8.0 if a.tts else 14.0, "speech_seconds_combined": 14.0,
                       "tts_used": a.tts, "voice_preset": a.voice if a.tts else None},
        "render": {"audio_mode": "mic_stem", "mic_source": "stream:1", "mic_gain": 1.0, "layout": "blur", "captions": "OFF"},
        "technical_qa": {"status": "PASS_TECHNICAL_ONLY"},
        "fingerprint_precheck": {"status": "NO_MATCH_DB", "tool": "fixture"},
        "overlay_scan": {"file_sha256": gatelog.sha256_file(out / "short_01.mp4"), "methods": ["fixture"],
                         "flagged": {"no": False, "yes": True, "unknown": None}[a.overlay_flagged], "regions": []}}
if a.upscale:
    clip["render"].update({"upscale": a.upscale, "output_resolution": {"2160": "2160x3840", "1440": "1440x2560"}.get(a.upscale, a.upscale)})
if a.mixed:
    clip["commentary"] = {"path": None, "mic_source": None, "tts_used": False, "mixed_track_speech_share": 0.7}
    clip["render"] = {"audio_mode": "source", "mic_source": None, "music_volume": 1.0, "layout": "blur", "captions": "OFF"}
effects = []
if a.edit != "off":
    effects = edit_gates.parse_effects(a.effects) if a.effects is not None else (["captions"] if a.edit == "clean" else ["punch_in", "end_fade"])
    effects = sorted(set(effects), key=edit_gates.EFFECTS.index)   # same order edit_gates.validate_choice records
    clip["render"].update({"edit_style": a.edit, "edit_effects": effects, "pre_edit_file": "short_01.preedit.mp4"})
    if a.flash_cuts:
        clip["render"].update({"flash_cuts": [5.0 * (i + 1) for i in range(a.flash_cuts)], "flash_intensity": a.flash_intensity})
if a.captions is not None:
    words = [{"word": w, "start": round(a.caption_start + i * 0.5, 2), "end": round(a.caption_start + i * 0.5 + 0.4, 2)}
             for i, w in enumerate(a.captions.split())]
    if not a.raw_profanity:
        words = edit_gates.mask_words(words)
    (out / "short_01.words.json").write_text(json.dumps(words, indent=1))
    flags = edit_gates.caption_flags(words)
    clip["render"].update({"captions": "BURNED_WORD_BY_WORD_NEEDS_HUMAN_CHECK", "caption_style": "word-pop-yellow",
                           "caption_source": "mic_stream:1", "words_json": "short_01.words.json",
                           "words_json_sha256": edit_gates.sha256_bytes(out / "short_01.words.json"),
                           "caption_review": {**flags, "warnings": edit_gates.flag_reasons(flags)}})
compliance.init_clip(clip)
(out / "manifest.json").write_text(json.dumps({"clips": [clip]}))
base = ["--output", str(out), "--clip", "short_01.mp4"]
if a.edit != "off" and not a.no_edit_choice:
    review.main(["edit", *base, "--style", a.edit, "--effects", ",".join(effects) or "none", "--by", "Tester", "--no-render"]
                + (["--flash-intensity", str(a.flash_intensity)] if "flash_cut" in effects else []))
if a.captions is not None and not a.skip_caption_review:
    review.main(["signoff", *base, "--check", "captions_reviewed", "--by", "Tester", "--note", a.caption_note])
if a.tts:
    sf = pathlib.Path(a.script_file) if a.script_file else work / "script.txt"
    if not a.script_file:
        sf.write_text(script_for(a.script_variant))
    review.main(["script", *base, "--file", str(sf), "--by", "Tester"])
for check in ("vod_rights_confirmed", "no_story_cutscene", "music_risk_cleared"):
    review.main(["signoff", *base, "--check", check, "--by", "Tester", "--note", "watched the whole clip, gameplay only"])
review.main(["signoff", *base, "--check", "overlays_third_parties_cleared", "--by", "Tester", "--note", a.overlay_note])
if a.mixed:
    review.main(["signoff", *base, "--check", "mixed_track_commentary_confirmed", "--by", "Tester", "--note", a.mixed_note])
if a.paid != "skip":
    review.main(["paid", *base, "--value", a.paid, "--by", "Tester"])
review.main(["approve", *base, "--by", "Tester"])
review.main(["export", *base, "--packages", str(work / "packages")])
pkg = next((work / "packages").iterdir())
print("PACKAGE_DIR=" + str(pkg))
