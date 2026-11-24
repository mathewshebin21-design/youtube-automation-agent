"""Human review CLI for CutsceneCity candidates. Nothing here talks to YouTube.

  python review.py status    --output output [--clip short_01.mp4]
  python review.py set       --output output --clip short_01.mp4 --file clip-details.json
  python review.py precheck  --output output --clip short_01.mp4
  python review.py commentary --output output --clip short_01.mp4 --mic mic.wav|--mic-stream 1 [--audio voiceover.wav [--tts --voice-preset NAME]]
  python review.py edit      --output output --clip short_01.mp4 --style off|clean|hype --effects captions,punch_in,... --by "Shebin" [--caption-style NAME] [--flash-intensity 0.5] [--no-render]
  python review.py script    --output output --clip short_01.mp4 --file script.txt --by "Shebin" [--note "..."]
  python review.py signoff   --output output --clip short_01.mp4 --check no_story_cutscene --by "Shebin" --note "..."
  python review.py approve   --output output --clip short_01.mp4 --by "Shebin"
  python review.py export    --output output --clip short_01.mp4 [--packages packages]
"""
import argparse
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import compliance  # noqa: E402
import edit_gates  # noqa: E402
import gatelog  # noqa: E402
import qa  # noqa: E402

HERE = pathlib.Path(__file__).parent
SETTABLE = {"metadata", "transformation_note", "ai_visuals_used"}  # provenance comes only from yt-dlp metadata


def policy():
    p = json.loads((HERE / "editorial-policy.json").read_text())
    compliance.load_extra_checks(p)
    return p


def ctx(pol, root):
    return compliance.build_ctx(pol, HERE)


def load(root):
    return json.loads((root / "manifest.json").read_text())


def save(root, manifest):
    manifest["publishing_allowed"] = False
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))


def find(manifest, name):
    for c in manifest["clips"]:
        if c["file"] == name:
            return c
    raise SystemExit(f"no clip {name} in manifest")


def source_video(root):
    return next((p for p in root.glob("vod.*") if p.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}), None)


FIX_COMMANDS = {
    "metadata_spoiler_free": "write title (+ your description text above the credit line) in details.json, then: review.py set --clip {c} --file details.json --by NAME",
    "attribution": "keep the credit line in the description (streamer + VOD URL), then: review.py set --clip {c} --file details.json --by NAME",
    "transformation_note": "add \"transformation_note\" (25+ words, your own) to details.json, then: review.py set --clip {c} --file details.json --by NAME",
    "paid_promotion_declared": "suggested value 'none' (NOT declared yet): review.py paid --clip {c} --value none --by NAME  (or --value present)",
    "technical_qa": "re-render (pipeline.py --render or review.py commentary) so qa.py runs on the final file",
    "original_commentary": "OBS mic track: review.py commentary --clip {c} --mic-stream N ; or mixed track: review.py signoff --clip {c} --check mixed_track_commentary_confirmed --by NAME --note \"<5+ words: live commentary audible>\"",
    "live_reaction_preserved": "same as original_commentary",
    "mixed_track_commentary_confirmed": "review.py precheck --clip {c}; listen; review.py signoff --clip {c} --check mixed_track_commentary_confirmed --by NAME --note \"<5+ words>\"",
    "commentary_script": "review.py script --clip {c} --file script.txt --by NAME",
    "captions_reviewed": "read {c} words.json against the video, then: review.py signoff --clip {c} --check captions_reviewed --by NAME --note \"<5+ words if flagged>\"",
    "style_rotation": "edits need a per-clip choice: review.py edit --clip {c} --style clean|hype --effects ... --by NAME",
}


def cmd_status(a, root, m, c_ctx):
    clips = [find(m, a.clip)] if a.clip else m["clips"]
    for c in clips:
        b = compliance.blockers(c, c_ctx)
        todo = {}
        for name in b:
            spec = compliance.CHECKS.get(name, {})
            if name in FIX_COMMANDS:
                todo[name] = FIX_COMMANDS[name].format(c=c["file"])
            elif spec.get("kind") == "human":
                todo[name] = f"review.py signoff --clip {c['file']} --check {name} --by NAME --note \"...\""
        md = c.get("metadata") or {}
        missing = [k for k, ok in (("title", md.get("title")), ("transformation_note (25+ words)", len(str(c.get("transformation_note", "")).split()) >= 25))
                   if not ok]
        print(json.dumps({"clip": c["file"], "blocking": b, "ready_to_approve": not b, "missing_creative_input": missing,
                          "commentary_source": (c.get("commentary") or {}).get("commentary_source"),
                          "paid_promotion": (c.get("paid_promotion") or {}).get("value") or
                          f"NOT DECLARED (suggestion: {c.get('paid_promotion_suggestion', 'none')})",
                          "synthetic_disclosure": {"containsSyntheticMedia": md.get("containsSyntheticMedia"),
                                                   "reason": c.get("synthetic_disclosure_reason")},
                          "how_to_fix": todo}, indent=2))


def cmd_set(a, root, m, c_ctx):
    c = find(m, a.clip)
    data = json.loads(pathlib.Path(a.file).read_text())
    bad = set(data) - SETTABLE
    if bad:
        raise SystemExit("not settable here: " + ", ".join(sorted(bad)))
    c.update(data)
    if c.get("metadata", {}).get("privacyStatus") not in (None, "private"):
        raise SystemExit("privacyStatus can only be private")
    compliance.evaluate(c, c_ctx)
    gatelog.append_review(root / "review_log.jsonl", action="set", by=a.by or "unknown", clip=c["file"],
                          fields=sorted(data), metadata_sha256=gatelog.sha256_json(c.get("metadata", {})))


def cmd_precheck(a, root, m, c_ctx):
    c = find(m, a.clip)
    src = source_video(root)
    c["cutscene_scan"] = {"letterbox_ratio": compliance.letterbox_ratio(src, c["start"], c["end"]) if src else None,
                          "method": "letterbox heuristic; human sign-off still required"}
    c["fingerprint_precheck"] = compliance.fingerprint(root / c["file"])
    if compliance.is_mixed_track(c):
        c.setdefault("commentary", {})["mixed_track_speech_share"] = compliance.mixed_speech_share(root / c["file"])
    c["overlay_scan"] = overlay_precheck(root, c)
    compliance.evaluate(c, c_ctx)
    print(json.dumps({k: c[k] for k in ("cutscene_scan", "fingerprint_precheck", "overlay_scan")}, indent=2))


def overlay_precheck(root, c):
    """Phase 2.7: scan the PRE-EDIT render (before our captions/effects) so our own captions never raise flags.
    Fallback: final render with the caption band + progress bar masked. The result is bound to the FINAL file hash."""
    import edit as edit_stage
    import overlay_scan
    r = c.get("render") or {}
    final = root / c["file"]
    final_sha = gatelog.sha256_file(final)
    pre = root / r["pre_edit_file"] if r.get("pre_edit_file") else None
    if pre is not None and pre.exists() and edit_gates.sha256_bytes(pre) == r.get("pre_edit_sha256"):
        res = overlay_scan.scan(pre, final_sha)
        res.update({"scanned": "pre_edit", "scanned_file": pre.name, "scanned_sha256": r["pre_edit_sha256"]})
    elif edit_gates.captions_burned(r) or (r.get("edit_style") or "off") != "off":
        res = overlay_scan.scan(final, final_sha, mask_bands=[edit_stage.CAPTION_BAND, edit_stage.PROGRESS_BAND])
        res["scanned"] = "final_caption_band_masked"
    else:
        res = overlay_scan.scan(final, final_sha)
        res["scanned"] = "final_no_edit"
    return res


PAID_STATEMENTS = {
    "none": "No sponsor overlay, sponsor read, paid product placement or endorsement appears in this file.",
    "present": "This file contains a paid promotion (sponsor overlay, read, product placement or endorsement).",
}


def cmd_paid(a, root, m, c_ctx):
    """Signed reviewer declaration for paidProductPlacementDetails (sent explicitly on upload)."""
    c = find(m, a.clip)
    if a.value not in compliance.PAID_VALUES:
        raise SystemExit("--value must be none or present")
    if not (a.by or "").strip():
        raise SystemExit("--by is required")
    e = gatelog.append_review(root / "review_log.jsonl", action="paid_promotion", value=a.value, by=a.by.strip(),
                              clip=c["file"], file_sha256=gatelog.sha256_file(root / c["file"]),
                              statement=PAID_STATEMENTS[a.value], note=a.note or "")
    c["paid_promotion"] = {"value": a.value, "by": e["by"], "at": e["at"], "log_seq": e["seq"]}
    compliance.evaluate(c, c_ctx)
    print(f"paid_promotion={a.value} signed (log entry {e['seq']})")


def commentary_bus(src, start, end, mic=None, mic_stream=None, voice=None):
    """Write the commentary bus (creator mic + optional voiceover/TTS) for the clip to a temp wav for VAD."""
    import subprocess
    import tempfile
    out = pathlib.Path(tempfile.mkstemp(suffix=".wav")[1])
    args = ["ffmpeg", "-v", "error", "-y"]
    if mic:
        args += ["-ss", str(start), "-t", str(end - start), "-i", str(mic)]
        mic_label = "0:a"
    else:
        args += ["-ss", str(start), "-t", str(end - start), "-i", str(src)]
        mic_label = f"0:a:{int(mic_stream)}"
    if voice:
        args += ["-i", str(voice)]
        graph = f"[{mic_label}]volume=1.0[m];[1:a]volume=1.0[c];[m][c]amix=inputs=2:duration=first:normalize=0[o]"
    else:
        graph = f"[{mic_label}]anull[o]"
    args += ["-filter_complex", graph, "-map", "[o]", "-ac", "1", "-ar", "16000", str(out)]
    if subprocess.run(args, capture_output=True).returncode != 0:
        out.unlink(missing_ok=True)
        raise SystemExit("could not read the creator mic stem (wrong --mic-stream index or file?); failing closed")
    return out


def cmd_commentary(a, root, m, c_ctx):
    import render
    c = find(m, a.clip)
    src = source_video(root)
    if not src:
        raise SystemExit("source VOD not in output dir; cannot re-render with commentary")
    if not a.mic and a.mic_stream is None:
        raise SystemExit("a separate creator mic stem is required (--mic FILE on the VOD timeline, or --mic-stream N "
                         "for an OBS multitrack recording). Twitch VODs have one mixed track: failing closed.")
    if a.tts and not a.voice_preset:
        raise SystemExit("--tts needs --voice-preset (rotation rule)")
    voice = pathlib.Path(a.audio).resolve() if a.audio else None
    live_wav = commentary_bus(src, c["start"], c["end"], a.mic, a.mic_stream)
    comb_wav = commentary_bus(src, c["start"], c["end"], a.mic, a.mic_stream, voice) if voice else live_wav
    live, combined = compliance.speech_seconds(live_wav), compliance.speech_seconds(comb_wav)
    for w in {live_wav, comb_wav}:
        w.unlink(missing_ok=True)
    if a.captions or a.edit_style not in (None, "off", "none"):
        raise SystemExit("phase 2.7: captions/edit style are a per-clip human choice: after this re-render run "
                         "review.py edit --clip ... --style ... --effects ... --by NAME (captions need this mic stem)")
    prev = c.get("render") or {}
    c["render"] = render.render(src, c["start"], c["end"], root, c["file"], captions=a.captions,
                                layout=prev.get("layout", "blur"), crop_x=prev.get("crop_x", 0.5),
                                facecam=prev.get("facecam"), audio_mode="mix" if a.keep_game_audio else "mic_stem",
                                keep_game_audio=bool(a.keep_game_audio),
                                game_volume=render.music_volume(a.music_volume), commentary=str(voice) if voice else None,
                                mic=a.mic, mic_stream=a.mic_stream, blur_regions=prev.get("blur_regions") or [],
                                upscale=a.upscale, joins=c.get("joins") or [],
                                edit_choice=recorded_choice(c))   # the signed per-clip edit choice, if any
    c["render"]["facecam"] = prev.get("facecam")
    c["render"]["profile"] = prev.get("profile")
    c["commentary"] = {"path": str(voice) if voice else None, "mic_source": c["render"]["mic_source"],
                       "speech_seconds_live": round(live, 2), "speech_seconds_combined": round(combined, 2),
                       "vad": "ffmpeg silencedetect energy VAD (-35 dB, 0.4 s) on the commentary bus",
                       "tts_used": bool(a.tts), "voice_preset": a.voice_preset if a.tts else None,
                       "commentary_source": "mic_stem",
                       "sha256": gatelog.sha256_file(voice) if voice else None}
    if a.tts:
        c.setdefault("metadata", {})["containsSyntheticMedia"] = True  # (e) forced, not optional
    c["technical_qa"] = qa.validate(root / c["file"], c["start"], c["end"])
    reset_human_signoffs(c, "file re-rendered with commentary")
    compliance.evaluate(c, c_ctx)
    print(json.dumps({"commentary": c["commentary"], "gate": c["compliance"]["original_commentary"]}, indent=2))


def recorded_choice(c):
    ec = c.get("edit_choice")
    return {k: ec[k] for k in ("edit_style", "effects", "by", "flash_intensity_pct", "caption_style")} if ec else None


def cmd_edit(a, root, m, c_ctx):
    """Record the per-clip human edit choice (signed), then re-render with it using the clip's previous audio setup."""
    import render
    c = find(m, a.clip)
    if not (a.by or "").strip():
        raise SystemExit("--by is required: the edit style and effects are a human choice")
    try:
        a.style = a.style or edit_gates.DEFAULT_CHOICE_STYLE
        effects = edit_gates.parse_effects(a.effects if a.effects is not None or a.style != "clean" else "captions")
        pct = None if a.flash_intensity is None else int(round(a.flash_intensity * 100))
        if a.flash_intensity is not None and a.flash_intensity > edit_gates.FLASH_MAX_INTENSITY:
            raise ValueError(f"flash intensity must be <= {edit_gates.FLASH_MAX_INTENSITY}")
        choice = edit_gates.validate_choice({"edit_style": a.style, "effects": effects, "by": a.by,
                                             "flash_intensity_pct": pct, "caption_style": a.caption_style or ""})
    except ValueError as e:
        raise SystemExit(f"edit choice refused: {e}")
    if choice["caption_style"] and choice["caption_style"] not in render.edit_stage.WORD_STYLES:
        raise SystemExit(f"--caption-style must be one of {sorted(render.edit_stage.WORD_STYLES)}")
    prev = c.get("render") or {}
    if "captions" in choice["effects"] and prev.get("audio_mode") not in ("mix", "mic_stem"):
        raise SystemExit("edit choice refused: " + edit_gates.MIC_REQUIRED +
                         " (run review.py commentary --mic FILE | --mic-stream N first)")
    e = gatelog.append_review(root / "review_log.jsonl", action="edit_choice", by=choice["by"], clip=c["file"],
                              edit_style=choice["edit_style"], effects=choice["effects"],
                              flash_intensity_pct=choice["flash_intensity_pct"], caption_style=choice["caption_style"],
                              note=a.note or "")
    c["edit_choice"] = {**choice, "at": e["at"], "log_seq": e["seq"]}
    if a.no_render:
        compliance.evaluate(c, c_ctx)
        print(json.dumps({"edit_choice": c["edit_choice"], "rendered": False}, indent=2))
        return
    src = source_video(root)
    if not src:
        raise SystemExit("source VOD not in output dir; cannot re-render with the edit")
    opts = {"layout": prev.get("layout", "blur"), "crop_x": prev.get("crop_x", 0.5), "facecam": prev.get("facecam"),
            "blur_regions": prev.get("blur_regions") or [], "audio_mode": prev.get("audio_mode") or "source",
            "joins": c.get("joins") or [], "edit_choice": recorded_choice(c)}
    up = str(prev.get("upscale") or "")
    opts["upscale"] = up if up in ("1440", "2160", "off") else None
    if opts["audio_mode"] in ("mix", "mic_stem"):
        ms = str(prev.get("mic_source") or "")
        if ms.startswith("stream:"):
            opts["mic_stream"] = int(ms.split(":", 1)[1])
        elif prev.get("mic_path"):
            opts["mic"] = prev["mic_path"]
        else:
            raise SystemExit("previous render has no reusable mic stem: run review.py commentary --mic FILE again")
        if (c.get("commentary") or {}).get("path"):
            opts["commentary"] = c["commentary"]["path"]
    if opts["audio_mode"] != "mic_stem":
        opts["game_volume"] = float(prev.get("music_volume") or 1.0)
    if opts["audio_mode"] == "mix":
        opts["keep_game_audio"] = bool(prev.get("keep_game_audio_opt_in"))
    try:
        c["render"] = render.render(src, c["start"], c["end"], root, c["file"], **opts)
    except ValueError as err:
        raise SystemExit(f"edit refused: {err}")
    for k in ("facecam", "profile"):
        c["render"][k] = prev.get(k)
    c["technical_qa"] = qa.validate(root / c["file"], c["start"], c["end"])
    if compliance.is_mixed_track(c):
        c.setdefault("commentary", {})["mixed_track_speech_share"] = compliance.mixed_speech_share(root / c["file"])
    reset_human_signoffs(c, "file re-rendered with a new edit choice")
    compliance.evaluate(c, c_ctx)
    print(json.dumps({"edit_choice": c["edit_choice"], "render": {k: c["render"].get(k) for k in (
        "edit_style", "edit_effects", "captions", "caption_source", "words_json", "caption_review", "zoom_count",
        "flash_cuts", "pre_edit_file")}}, indent=2))


def cmd_script(a, root, m, c_ctx):
    """Store the human-edited commentary script and approve it in the signed log (gate 4a)."""
    import script_checks
    c = find(m, a.clip)
    if not (a.by or "").strip():
        raise SystemExit("--by is required")
    text = pathlib.Path(a.file).read_text().strip()
    status, why, sim = script_checks.check_script(text, c_ctx.get("script_history", []), script_checks.clip_key(c))
    if status == "FAIL":
        raise SystemExit("script rejected: " + why)
    if status == "WARN" and len((a.note or "").split()) < 5:
        raise SystemExit(why + "; re-run with --note \"<why this is still original, 5+ words>\"")
    sha = compliance._sha(text)
    e = gatelog.append_review(root / "review_log.jsonl", action="script_approve", by=a.by.strip(), clip=c["file"],
                              script_sha256=sha, similarity_pct=int(round(sim * 100)), note=a.note or "")  # ints only in signed records
    c["commentary_script"] = {"text": text, "approved_sha256": sha, "approved_by": e["by"], "at": e["at"],
                              "similarity": round(sim, 3), "similarity_note": a.note or "", "edited_by_human": True}
    compliance.evaluate(c, c_ctx)
    print(f"script approved (overlap {sim:.0%}); log entry {e['seq']}")


def reset_human_signoffs(c, why):
    for name, spec in compliance.CHECKS.items():
        if spec["kind"] == "human" and c["compliance"].get(name, {}).get("status") == "PASS":
            c["compliance"][name] = {"status": "PENDING", "revoked": why}
    c.pop("human_approval", None)
    c.pop("overlay_scan", None)      # scan belongs to the old render
    c.pop("paid_promotion", None)    # declaration is bound to the old file hash


def unsigned_human_checks(c, entries, file_sha, root=None):
    """Human PASS entries in the manifest must be backed by a signed sign-off for the current file."""
    signed = {e["check"] for e in entries if e.get("action") == "signoff" and e.get("clip") == c["file"]
              and e.get("file_sha256") == file_sha}
    out = [n for n in compliance.required_human_checks(c) if n not in signed]
    paid = (c.get("paid_promotion") or {}).get("value")
    if not any(e.get("action") == "paid_promotion" and e.get("clip") == c["file"] and e.get("value") == paid
               and e.get("file_sha256") == file_sha for e in entries):
        out.append("paid_promotion (no signed declaration for this file)")
    if (c.get("overlay_scan") or {}).get("file_sha256") != file_sha:
        out.append("overlay_scan (not run on this exact file)")
    script = (c.get("commentary_script") or {}).get("text")
    if script:
        ok = any(e.get("action") == "script_approve" and e.get("clip") == c["file"]
                 and e.get("script_sha256") == compliance._sha(script) for e in entries)
        if not ok:
            out.append("commentary_script (no signed script approval)")
    r = c.get("render") or {}
    out += edit_gates.signed_problems(c, entries, file_sha, root / r["words_json"] if (root and r.get("words_json")) else None)
    return out


def cmd_signoff(a, root, m, c_ctx):
    c = find(m, a.clip)
    if a.check == "overlays_third_parties_cleared" and (c.get("overlay_scan") or {}).get("file_sha256") != gatelog.sha256_file(root / c["file"]):
        raise SystemExit("overlay scan is missing or for an older render: run review.py precheck first")
    if a.check == "mixed_track_commentary_confirmed" and len((a.note or "").split()) < 5:
        raise SystemExit("mixed_track_commentary_confirmed needs --note with 5+ words saying the live commentary is audible")
    extra = {}
    if a.check == "captions_reviewed":
        r = c.get("render") or {}
        wp = root / r["words_json"] if r.get("words_json") else None
        if not wp or not wp.exists() or edit_gates.sha256_bytes(wp) != r.get("words_json_sha256"):
            raise SystemExit("captions_reviewed: words.json is missing or changed since the render; re-render")
        flags = edit_gates.caption_flags(json.loads(wp.read_text()), c_ctx.get("policy"))
        if flags["unmasked_profanity"]:
            raise SystemExit("captions_reviewed: unmasked strong profanity in words.json; re-render")
        if edit_gates.flag_reasons(flags) and len((a.note or "").split()) < 5:
            raise SystemExit("captions_reviewed is flagged (" + "; ".join(edit_gates.flag_reasons(flags)) +
                             "): --note with 5+ words is required")
        extra["words_json_sha256"] = r["words_json_sha256"]
    entry = compliance.signoff(c, a.check, a.by or "", a.note or "", c_ctx)
    if a.check == "mixed_track_commentary_confirmed":
        c.setdefault("commentary", {})["commentary_source"] = "mixed_track_signed"
        compliance.evaluate(c, c_ctx)
    gatelog.append_review(root / "review_log.jsonl", action="signoff", check=a.check, by=entry["by"], note=entry["note"],
                          clip=c["file"], file_sha256=gatelog.sha256_file(root / c["file"]), **extra)


def cmd_approve(a, root, m, c_ctx):
    c = find(m, a.clip)
    b = compliance.blockers(c, c_ctx)
    entries = gatelog.verify_review_log(root / "review_log.jsonl") if (root / "review_log.jsonl").exists() else []
    unsigned = unsigned_human_checks(c, entries, gatelog.sha256_file(root / c["file"]), root)
    if unsigned:
        b.update({n: "no signed sign-off for the current file" for n in unsigned})
    if b:
        raise SystemExit("cannot approve, blocking checks:\n" + json.dumps(b, indent=2))
    if not (a.by or "").strip():
        raise SystemExit("--by is required")
    e = gatelog.append_review(root / "review_log.jsonl", action="approve", by=a.by.strip(), clip=c["file"],
                              file_sha256=gatelog.sha256_file(root / c["file"]),
                              metadata_sha256=gatelog.sha256_json(c["metadata"]),
                              provenance_sha256=gatelog.sha256_json(c["provenance"]),
                              script_sha256=compliance._sha((c.get("commentary_script") or {}).get("text") or ""),
                              paid_promotion=(c.get("paid_promotion") or {}).get("value"),
                              statement="I watched the whole final file and approve a PRIVATE upload of exactly this file and metadata.")
    c["human_approval"] = {"status": "APPROVED_FOR_PRIVATE_UPLOAD", "by": e["by"], "at": e["at"], "log_seq": e["seq"]}
    import script_checks
    script_checks.record(script_checks.clip_key(c), (c.get("commentary_script") or {}).get("text") or "",
                         (c.get("commentary") or {}).get("voice_preset"), (c.get("render") or {}).get("caption_style"))
    print(f"approved {c['file']} (log entry {e['seq']})")


def build_package(root, c, packages, c_ctx):
    b = compliance.blockers(c, c_ctx)
    if b:
        raise SystemExit("cannot export, blocking checks:\n" + json.dumps(b, indent=2))
    entries = gatelog.verify_review_log(root / "review_log.jsonl")
    appr = gatelog.latest_approval(entries, c["file"])
    file_sha = gatelog.sha256_file(root / c["file"])
    unsigned = unsigned_human_checks(c, entries, file_sha, root)
    if unsigned:
        raise SystemExit("human checks without a signed sign-off for this exact file: " + ", ".join(unsigned))
    if (not appr or appr["file_sha256"] != file_sha or appr["metadata_sha256"] != gatelog.sha256_json(c["metadata"])
            or appr.get("provenance_sha256") != gatelog.sha256_json(c["provenance"])
            or appr.get("script_sha256") != compliance._sha((c.get("commentary_script") or {}).get("text") or "")
            or appr.get("paid_promotion") != (c.get("paid_promotion") or {}).get("value")):
        raise SystemExit("no signed approval for this exact file + metadata; run review.py approve again")
    md = c["metadata"]
    upload = {"title": md["title"], "description": md["description"], "tags": md.get("tags", [])[:15],
              "categoryId": str(md.get("categoryId", "20")),
              "containsSyntheticMedia": bool(md["containsSyntheticMedia"]),
              "privacyStatus": "private", "selfDeclaredMadeForKids": False,
              "paidProductPlacement": c["paid_promotion"]["value"] == "present"}
    pkg = {"schema": "cutscenecity.upload-package/4",
           "style": {"voice_preset": (c.get("commentary") or {}).get("voice_preset") or "",
                     "caption_style": (c.get("render") or {}).get("caption_style") or "",
                     "edit_style": (c.get("render") or {}).get("edit_style") or "off",
                     "edit_effects": list((c.get("render") or {}).get("edit_effects") or [])},
           "captions": ({"file": edit_gates.WORDS_PACKAGE_NAME, "words_json_sha256": c["render"]["words_json_sha256"]}
                        if edit_gates.captions_burned(c.get("render")) else None),
           "clip": c["file"], "upload": upload, "file_sha256": file_sha,
           "source": {"url": c["provenance"]["source_url"], "vod_id": gatelog.vod_id(c["provenance"]["source_url"]),
                      "channel": c["provenance"]["source_channel_name"],
                      "start_ms": int(round(float(c["start"]) * 1000)), "end_ms": int(round(float(c["end"]) * 1000))},
           "approval": {k: appr[k] for k in ("seq", "by", "at", "sig")}}
    pkg["package_sha256"] = gatelog.sha256_json(pkg)
    out = pathlib.Path(packages) / (pathlib.Path(c["file"]).stem + "-" + pkg["package_sha256"][:12])
    out.mkdir(parents=True, exist_ok=False)
    shutil.copy2(root / c["file"], out / "video.mp4")
    if pkg["captions"]:
        shutil.copy2(root / c["render"]["words_json"], out / edit_gates.WORDS_PACKAGE_NAME)
    (out / "package.json").write_text(json.dumps(pkg, indent=2))
    (out / "clip.json").write_text(json.dumps(c, indent=2))
    shutil.copy2(root / "review_log.jsonl", out / "review_log.jsonl")
    # Field names match the fork's Shorts clip rows (privacyStatus/containsSyntheticMedia/captionsPath/provenance)
    (out / "agent-import.json").write_text(json.dumps({
        "schema": "cutscenecity.agent-import/1", "type": "external_short", "videoPath": str((out / "video.mp4").resolve()), "privacyStatus": "private",
        "containsSyntheticMedia": upload["containsSyntheticMedia"], "paidProductPlacement": upload["paidProductPlacement"], "title": upload["title"],
        "description": upload["description"], "tags": upload["tags"], "captionsPath": None,
        "provenance": c["provenance"], "selfDeclaredMadeForKids": False,
        "approvedBy": appr["by"], "packageSha256": pkg["package_sha256"], "fileSha256": file_sha}, indent=2))
    return out, pkg


def cmd_export(a, root, m, c_ctx):
    out, pkg = build_package(root, find(m, a.clip), a.packages, c_ctx)
    print(json.dumps({"package": str(out), "package_sha256": pkg["package_sha256"]}, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["status", "set", "precheck", "commentary", "edit", "script", "paid", "signoff", "approve", "export"])
    p.add_argument("--value", help="paid: none | present")
    p.add_argument("--output", default="output")
    p.add_argument("--clip")
    p.add_argument("--file")
    p.add_argument("--audio")
    p.add_argument("--mic", help="creator mic stem file on the VOD timeline")
    p.add_argument("--mic-stream", type=int, help="audio stream index of the mic in an OBS multitrack source")
    p.add_argument("--voice-preset", help="TTS voice preset name from editorial-policy.json (rotation)")
    p.add_argument("--caption-style", help="edit: word caption style from editorial-policy.json word_caption_styles (rotation)")
    p.add_argument("--style", default=None, help="edit: clean (default) | hype (opt-in) | off; per-clip human choice")
    p.add_argument("--effects", help="edit: comma list of " + ",".join(edit_gates.EFFECTS) + " allowed for the style, or none")
    p.add_argument("--flash-intensity", type=float, default=None, help="edit: flash_cut intensity, > 0 and <= 0.5 (default 0.5)")
    p.add_argument("--no-render", action="store_true", help="edit: record the choice only (applied at the next re-render)")
    p.add_argument("--tts", action="store_true")
    p.add_argument("--music-volume", type=float, default=None,
                   help="game/music bed level 0<v<=1 (default env CUTSCENECITY_MUSIC_VOLUME or 1.0 = original audio unchanged)")
    p.add_argument("--upscale", default=None, help="commentary re-render: 2160 (default) | 1440 | off; env CUTSCENECITY_UPSCALE")
    p.add_argument("--strip-game-audio", action="store_true", help="default since phase 2.7 (kept for old scripts; no effect)")
    p.add_argument("--keep-game-audio", action="store_true", help="opt-in: keep game/music audio under the mic (audio_mode mix)")
    p.add_argument("--edit-style", default=None, help=argparse.SUPPRESS)   # phase 2.7: use review.py edit
    p.add_argument("--captions", action="store_true", help=argparse.SUPPRESS)  # phase 2.7: review.py edit --effects captions
    p.add_argument("--check")
    p.add_argument("--by")
    p.add_argument("--note")
    p.add_argument("--packages", default="packages")
    a = p.parse_args(argv)
    root = pathlib.Path(a.output)
    pol = policy()
    m = load(root)
    for c in m["clips"]:
        compliance.init_clip(c)
    globals()["cmd_" + a.command](a, root, m, ctx(pol, root))
    save(root, m)


if __name__ == "__main__":
    main()
