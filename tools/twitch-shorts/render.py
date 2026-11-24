"""9:16 rendering options for review candidates. All commands are argument lists (no shell).

Layouts:
  pad    - original letterbox (PR #1 behaviour, keeps the full frame/HUD)
  blur   - full frame centred over a blurred, zoomed copy of itself (no black bars)
  crop   - centre crop; --crop-x 0..1 moves the crop, or "smart" uses the motion centroid
  split  - facecam box on top, gameplay crop below (box given as fractions x,y,w,h of the source)
Audio:
  Game audio is KEPT by default (Shebin, phase 2.8 override): mix = original game audio + the creator mic
  stem at gain 1.0 + an optional voiceover/TTS on top. Stripping it (mic_stem) is the opt-in.
  mix       - DEFAULT for upload renders: game audio (music volume, default 1.0 = unchanged) + the separate
              creator mic stem at full level + optional voiceover; no ducking.
  source    - the source audio only (+ optional voiceover on top); pipeline.py first render when no mic stem
              is given. Fails live_reaction_preserved / original_commentary until a mic stem is added.
  none      - video-only silent preview (no longer a default; kept for callers that want it)
  mic_stem  - opt-in (--strip-game-audio): drop game/music audio; keep the creator's separate mic track at full
              level (never ducked or muted) and add the voiceover/TTS track on top. The mic must be a separate stem:
              an OBS multitrack recording stream (--mic-stream N) or a mic file on the VOD timeline.
              Twitch VODs carry ONE mixed track, so the mic cannot be separated from them: fail closed.
Always ends with loudnorm to about -14 LUFS (single pass) applied to the whole mix (no ducking).
Blur regions (fractions x,y,w,h of the source frame) are blurred before the layout is applied.
"""
import json
import os
import pathlib
import subprocess

import edit as edit_stage

W, H = 1080, 1920
LOUDNORM = "loudnorm=I=-14:TP=-1.5:LRA=11"
LAYOUTS = ("pad", "blur", "crop", "split")


def parse_box(text):
    parts = [float(x) for x in str(text).split(",")]
    if len(parts) != 4 or not all(0 <= p <= 1 for p in parts) or parts[2] <= 0 or parts[3] <= 0:
        raise ValueError("facecam box must be four fractions x,y,w,h between 0 and 1")
    if parts[0] + parts[2] > 1.0001 or parts[1] + parts[3] > 1.0001:
        raise ValueError("facecam box falls outside the frame")
    return parts


def smart_crop_x(video, start, end, samples=12):
    """Horizontal motion centroid (0..1) over the clip; 0.5 if it cannot be measured."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return 0.5
    cap = cv2.VideoCapture(str(video))
    last, weights = None, None
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * (start + (end - start) * i / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(frame, (256, 144)), cv2.COLOR_BGR2GRAY).astype("float32")
        if last is not None:
            col = np.abs(g - last).sum(axis=0)
            weights = col if weights is None else weights + col
        last = g
    cap.release()
    if weights is None or weights.sum() == 0:
        return 0.5
    import numpy as np
    return float(np.clip((weights * np.arange(weights.size)).sum() / weights.sum() / (weights.size - 1), 0, 1))


def blur_chain(regions, src="0:v"):
    """Blur fixed regions (chat overlay, alerts, notifications) of the source before the 9:16 layout."""
    if not regions:
        return "", f"[{src}]"
    parts, last = [], src
    for i, r in enumerate(regions):
        x, y, w, h = parse_box(",".join(str(v) for v in r))
        parts.append(f"[{last}]split=2[bb{i}a][bb{i}b];[bb{i}b]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},boxblur=25:3[bb{i}c];"
                     f"[bb{i}a][bb{i}c]overlay=main_w*{x}:main_h*{y}[bb{i}o]")
        last = f"bb{i}o"
    return ";".join(parts) + ";", f"[{last}]"


def video_filter(layout, crop_x=0.5, facecam=None, facecam_height=640, blur_regions=None):
    """Return a filter_complex chain from [0:v] to [v]."""
    pre, src = blur_chain(blur_regions)
    if layout == "pad":
        body = f"{src}scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1[v]"
    elif layout == "blur":
        body = (f"{src}split=2[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2[bg];"
                f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    elif layout == "crop":
        x = min(max(float(crop_x), 0.0), 1.0)
        body = f"{src}scale=-2:{H},crop={W}:{H}:(iw-{W})*{x:.4f}:0,setsar=1[v]"
    elif layout == "split":
        if not facecam:
            raise ValueError("split layout needs --facecam-box x,y,w,h")
        fx, fy, fw, fh = facecam
        game_h = H - facecam_height
        x = min(max(float(crop_x), 0.0), 1.0)
        body = (f"{src}split=2[a][b];"
                f"[a]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},scale={W}:{facecam_height}:force_original_aspect_ratio=increase,crop={W}:{facecam_height}[cam];"
                f"[b]scale=-2:{game_h},crop={W}:{game_h}:(iw-{W})*{x:.4f}:0[game];"
                f"[cam][game]vstack=inputs=2,setsar=1[v]")
    else:
        raise ValueError(f"unknown layout {layout!r}; choose one of {LAYOUTS}")
    return pre + body


AUDIO_MODES = ("source", "mix", "mic_stem")  # mix (game audio kept) = default; mic_stem (game audio stripped) is opt-in
MUSIC_VOLUME_ENV = "CUTSCENECITY_MUSIC_VOLUME"


def music_volume(value=None):
    """Game/music bed level. Default 1.0 = original audio unchanged; 0 < v < 1 lowers it under commentary.
    Phase 2.8 override: game audio is kept by default (mix); this level is ignored only with --strip-game-audio."""
    raw = os.getenv(MUSIC_VOLUME_ENV, "1.0") if value is None else value
    v = float(raw)
    if not 0.0 < v <= 1.0:
        raise ValueError("music volume must be > 0 and <= 1.0 (game audio is kept by default; --strip-game-audio removes it)")
    return v


def audio_filter(mode, mic_label=None, voice_label=None, game_volume=1.0, game_label="0:a"):
    """Audio graph to [a]. Default keeps ALL original game audio (music, voices, cutscenes) at game_volume (1.0).
    The creator mic is never lowered: volume stays 1.0 and amix does not normalise. loudnorm = overall loudness only."""
    if mode not in AUDIO_MODES:
        raise ValueError("audio mode must be source, mix or mic_stem (mute/duck are not allowed: they would silence the creator)")
    g = f"{float(game_volume):g}" if game_volume != 1.0 else "1.0"
    if mode in ("source", "mix"):
        parts = [f"[{game_label}]volume={g}[s]"]
        ins = ["[s]"]
        if mode == "mix":
            if not mic_label:
                raise ValueError("mix needs a separate creator mic track (fail closed)")
            parts.append(f"[{mic_label}]volume=1.0[m]")
            ins.append("[m]")
        if voice_label:
            parts.append(f"[{voice_label}]volume=1.0[c]")
            ins.append("[c]")
        if len(ins) == 1:
            return f"[{game_label}]volume={g},{LOUDNORM}[a]"
        return ";".join(parts) + f";{''.join(ins)}amix=inputs={len(ins)}:duration=first:normalize=0,{LOUDNORM}[a]"
    if not mic_label:
        raise ValueError("mic_stem needs a separate creator mic track (fail closed)")
    if voice_label:
        return f"[{mic_label}]volume=1.0[m];[{voice_label}]volume=1.0[c];[m][c]amix=inputs=2:duration=first:normalize=0,{LOUDNORM}[a]"
    return f"[{mic_label}]volume=1.0,{LOUDNORM}[a]"


def _ts(sec):
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def build_command(video, start, end, out_name, layout="blur", crop_x=0.5, facecam=None, audio_mode="source",
                  commentary=None, mic=None, mic_stream=None, srt_name=None, has_source_audio=True, blur_regions=None,
                  caption_style=None, game_volume=1.0):
    """ffmpeg argv. Run it with cwd = output dir so the subtitles filter sees a plain relative file name."""
    vf = video_filter(layout, crop_x, facecam, blur_regions=blur_regions)
    if srt_name:
        if not all(c.isalnum() or c in "._-" for c in srt_name):
            raise ValueError("unsafe subtitle file name")
        style = caption_style or "FontName=Arial,FontSize=14,Outline=2,MarginV=230"
        if any(c in style for c in "'[];\\"):
            raise ValueError("unsafe caption style")
        vf = vf[:-3] + f",subtitles={srt_name}:force_style='{style}'[v]"
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-i", str(video)]
    idx = 1
    mic_label = voice_label = None
    if audio_mode == "none":
        if commentary:
            raise ValueError("audio_mode none is a silent preview: no commentary track")
        args += ["-t", str(end - start), "-filter_complex", vf, "-map", "[v]", "-an"]
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30",
                 "-movflags", "+faststart", out_name]
        return args
    if audio_mode in ("mic_stem", "mix"):
        if mic:
            args += ["-ss", str(start), "-i", str(mic)]
            mic_label, idx = f"{idx}:a", idx + 1
        elif mic_stream is not None:
            mic_label = f"0:a:{int(mic_stream)}"
        else:
            raise ValueError(f"{audio_mode} needs --mic or --mic-stream (fail closed)")
    if commentary:
        args += ["-i", str(commentary)]
        voice_label = f"{idx}:a"
    if audio_mode == "source" and not has_source_audio:
        af = f"[{voice_label}]{LOUDNORM}[a]" if voice_label else None
    else:
        game_label = "0:a:0" if (audio_mode == "mix" and mic_stream is not None) else "0:a"
        af = audio_filter(audio_mode, mic_label, voice_label, game_volume=game_volume, game_label=game_label)
    graph = vf + (";" + af if af else "")
    args += ["-t", str(end - start), "-filter_complex", graph, "-map", "[v]"]
    if af:
        args += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30",
             "-movflags", "+faststart", out_name]
    return args


def has_audio(video):
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json", str(video)],
                       capture_output=True, text=True)
    return p.returncode == 0 and bool(json.loads(p.stdout or "{}").get("streams"))


# ---------- upscale (ON by default: 2160x3840) ----------
UPSCALE_ENV = "CUTSCENECITY_UPSCALE"
UPSCALE_TARGETS = {"1440": (1440, 2560), "2160": (2160, 3840)}
DEFAULT_UPSCALE = "2160"


def upscale_setting(value=None):
    """'1440' | '2160' | None (off). Default 2160; 'off' (flag or env) is an opt-out for tests/debugging."""
    raw = str(value if value not in (None, "") else os.getenv(UPSCALE_ENV, DEFAULT_UPSCALE)).strip().lower()
    if raw in ("off", "0", "none", "false", "no"):
        return None
    if raw not in UPSCALE_TARGETS:
        raise ValueError("upscale must be 1440, 2160 or off")
    return raw


def video_size(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    s = json.loads(p.stdout)["streams"][0]
    return int(s["width"]), int(s["height"])


def upscale_command(src, dst, width, height):
    """Lanczos + mild unsharp; CRF 18 yuv420p +faststart; audio stream copied unchanged.
    Upscaling adds no real detail: it only lets YouTube serve its higher-bitrate (VP9/AV1 4K) encode."""
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a?",
            "-vf", f"scale={width}:{height}:flags=lanczos,unsharp=5:5:0.5:5:5:0.0", "-c:v", "libx264", "-preset", "medium",
            "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(dst)]


def upscale(path, setting):
    """Upscale the final render in place (after captions, before qa.py). Never above the target; skip if the
    source is already at or above it."""
    import time
    path = pathlib.Path(path)
    if setting is None:
        w, h = video_size(path)
        return {"upscale": "off", "output_resolution": f"{w}x{h}"}
    tw, th = UPSCALE_TARGETS[setting]
    w, h = video_size(path)
    if h >= th or w >= tw:
        return {"upscale": f"skipped (source {w}x{h} already >= {tw}x{th})", "output_resolution": f"{w}x{h}"}
    tmp = path.with_name(path.stem + ".upscale.tmp.mp4")
    t0 = time.monotonic()
    try:
        subprocess.run(upscale_command(path, tmp, tw, th), check=True)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return {"upscale": setting, "output_resolution": f"{tw}x{th}", "upscale_seconds": round(time.monotonic() - t0, 1),
            "upscale_method": "ffmpeg lanczos + unsharp 0.5, CRF 18, audio copied"}


def render(video, start, end, out_dir, out_name, captions=False, **opts):
    """Render one clip. Phase 2.7: the edit stage (captions/effects) runs only with a recorded per-clip human
    `edit_choice` ({edit_style, effects, by, ...}); edit_style other than off without one is refused. Captions come
    only from a separate mic stem. When an edit runs, the pre-edit render is kept as <stem>.preedit.mp4 so the
    overlay precheck scans frames without our own captions."""
    import edit_gates
    import shutil
    out_dir = pathlib.Path(out_dir)
    video = pathlib.Path(video).resolve()
    for key in ("commentary", "mic"):
        if opts.get(key):
            opts[key] = str(pathlib.Path(opts[key]).resolve())
    if opts.get("layout") in ("crop", "split") and opts.get("crop_x") == "smart":
        opts["crop_x"] = smart_crop_x(video, start, end)
    elif opts.get("crop_x") in (None, "smart"):
        opts["crop_x"] = 0.5
    if captions:
        raise edit_gates.CaptionSourceError("the old SRT --captions path was removed in phase 2.7: captions are a per-clip "
                                            "edit effect (review.py edit --effects captions) and need a separate mic stem")
    choice = opts.pop("edit_choice", None)
    asked = opts.pop("edit_style", None)
    if choice is not None:                                        # the recorded human choice wins over env defaults
        choice = edit_gates.validate_choice(choice)
        if asked not in (None, "") and edit_stage.edit_style(asked) != choice["edit_style"]:
            raise ValueError(f"edit style {asked} differs from the recorded human edit choice {choice['edit_style']}")
        style = choice["edit_style"]
    else:
        # No recorded human choice -> no edit (pre-edit render). An explicit style or env style is refused (fix 7);
        # the default choice (clean) is only applied once a human records it with review.py edit.
        asked = asked if asked not in (None, "") else (os.getenv(edit_stage.EDIT_ENV) or "off")
        style = edit_stage.edit_style(asked)
        if style != "off":
            raise ValueError(f"edit style {style} needs a recorded per-clip human edit choice (review.py edit --clip ... "
                             "--style ... --effects ... --by NAME); refusing to apply edits without one")
    joins = list(opts.pop("joins", None) or [])
    for legacy in ("flash_cut", "word_caption_style", "caption_style_name", "caption_style"):
        opts.pop(legacy, None)       # effects, flash and caption style now come only from the human edit choice
    cap_src = edit_gates.caption_source(opts)
    if choice and "captions" in choice["effects"] and not cap_src:
        raise edit_gates.CaptionSourceError(edit_gates.MIC_REQUIRED)
    if cap_src:
        cap_src = {**cap_src, "media": cap_src["media"] or str(video), "start": start}
    opts.pop("keep_game_audio", None)       # phase 2.8 override: game audio is kept by default; accepted as a no-op
    up_setting = upscale_setting(opts.pop("upscale", None))   # validate before spending time on the render
    args = build_command(video, start, end, out_name, has_source_audio=has_audio(video), **opts)
    subprocess.run(args, check=True, cwd=str(out_dir), env={**os.environ})
    pre = out_dir / (pathlib.Path(out_name).stem + ".preedit.mp4")
    pre_rec = {}
    if style != "off":
        shutil.copy2(out_dir / out_name, pre)                     # pre-edit render (no captions/effects) for the overlay scan
        pre_rec = {"pre_edit_file": pre.name, "pre_edit_sha256": edit_gates.sha256_bytes(pre)}
        ed = edit_stage.apply(out_dir / out_name, choice, joins=joins, caption_source=cap_src,
                              energy_source=(video, start) if has_audio(video) else None)   # captions/effects
    else:
        pre.unlink(missing_ok=True)                               # no stale pre-edit file from an older render
        ed = {"edit_style": "off", "edit_effects": [], **({"edit_choice_by": choice["by"]} if choice else {})}
    words = ed.pop("_words", edit_stage._NOT_TRANSCRIBED)
    if choice is not None and cap_src:                          # phase 2.8: audio profanity scan (+ bleep if chosen)
        ed["profanity_audio"] = edit_stage.audio_profanity(out_dir / out_name, choice, cap_src, words=words)
    elif choice is not None and choice.get("bleep", "off") != "off":
        raise edit_gates.CaptionSourceError("bleep needs a separate creator mic stem to find the word timestamps")
    caption_status = ed["word_captions"] if str(ed.get("word_captions", "")).startswith("BURNED") else "OFF"
    up = upscale(out_dir / out_name, up_setting)                                                       # then upscale
    return {**ed, **pre_rec, **up, "layout": opts.get("layout", "blur"), "crop_x": round(float(opts.get("crop_x", 0.5)), 3),
            "audio_mode": opts.get("audio_mode", "source"), "commentary_mixed": bool(opts.get("commentary")),
            "mic_source": (f"file:{pathlib.Path(opts['mic']).name}" if opts.get("mic") else
                           (f"stream:{opts['mic_stream']}" if opts.get("mic_stream") is not None else None)),
            "mic_path": opts.get("mic") or None,
            "mic_gain": 1.0 if opts.get("audio_mode") in ("mic_stem", "mix") else None,
            "game_audio": ("stripped (--strip-game-audio opt-in)" if opts.get("audio_mode") == "mic_stem" else
                           "none (silent preview)" if opts.get("audio_mode") == "none" else "kept (default)"),
            "strip_game_audio_opt_in": opts.get("audio_mode") == "mic_stem",
            "music_volume": None if opts.get("audio_mode") in ("mic_stem", "none") else float(opts.get("game_volume", 1.0)),
            "blur_regions": opts.get("blur_regions") or [],
            "caption_style": ed.get("word_caption_style") if caption_status != "OFF" else None,
            "captions": caption_status, "loudnorm": "I=-14 LUFS TP=-1.5 (single pass)"}
