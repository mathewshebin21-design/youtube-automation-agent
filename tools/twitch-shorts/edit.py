"""Automatic edit stage (captions/effects) for CutsceneCity Shorts. ffmpeg + libass only: no paid services,
no stock assets, no added music or SFX. Runs on the rendered 1080x1920 file, BEFORE upscale and qa.py.

Styles (--edit-style / env CUTSCENECITY_EDIT_STYLE, default "hype"):
  off   - no edit pass (old --captions SRT path still works)
  clean - word-by-word animated captions only
  hype  - captions + punch-in zooms on audio-energy spikes (max 1 per 4 s, ~1.15x, 0.3 s ease in/out),
          0.2 s shake on the top 1-2 spikes, 0.5 s 1.1->1.0 hook zoom-out, 0.3 s fade at the end,
          thin progress bar along the bottom edge. Optional white flash at joins of two adjacent picks
          (--flash-cut, off by default).
Audio is never touched: the edit pass copies the audio stream (-c:a copy), so music volume and loudness
from the render are kept exactly.
Captions are the exact faster-whisper words (only ASS control characters \\ { } are removed).
"""
import json
import os
import pathlib
import subprocess
import time

EDIT_ENV = "CUTSCENECITY_EDIT_STYLE"
EDIT_STYLES = ("off", "clean", "hype")
DEFAULT_EDIT_STYLE = "hype"
WHISPER_ENV = "CUTSCENECITY_WHISPER_MODEL"
FPS = 30
W, H = 1080, 1920
CAPTION_MARGIN_V = 360          # bottom 15% of 1920 = 288 px; captions sit above it
CAPTION_FONT = "Liberation Sans"
WORD_STYLES = {"word-pop-yellow": "&H00FFFF&", "word-pop-cyan": "&HFFFF00&", "word-pop-green": "&H00FF00&"}
DEFAULT_WORD_STYLE = "word-pop-yellow"
ZOOM = 1.15
EASE = 0.3                      # seconds, ease in and ease out
HOLD = 0.5                      # seconds at full zoom between ease in and ease out
MIN_GAP = 4.0                   # at most one punch-in every 4 s
SHAKE_SECONDS = 0.2
SHAKE_PX = 10
HOOK_SECONDS, HOOK_ZOOM = 0.5, 1.1
FADE_SECONDS = 0.3
BAR_PX = 10


def edit_style(value=None):
    raw = str(value if value not in (None, "") else os.getenv(EDIT_ENV, DEFAULT_EDIT_STYLE)).strip().lower()
    if raw not in EDIT_STYLES:
        raise ValueError("edit style must be off, clean or hype")
    return raw


# ---------- captions ----------
def transcribe_words(media, model=None):
    """[{word,start,end}] from faster-whisper word timestamps (seconds from the start of `media`).
    [] if faster-whisper is not installed or nothing was said. Never invents text."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    import numpy as np
    # Decode with ffmpeg and pass samples (avoids PyAV version issues inside faster-whisper).
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True, check=True)
    audio = np.frombuffer(p.stdout, dtype="<f4").copy()
    if audio.size == 0:
        return []
    name = model or os.getenv(WHISPER_ENV, "small")
    wm = WhisperModel(name, compute_type="int8")
    common = {"word_timestamps": True, "condition_on_previous_text": False}
    # Pass 1: Silero VAD (tuned lower: game audio under the voice). Pass 2 only if VAD finds nothing:
    # no VAD, with hallucination guards (low-confidence and repeated segments are dropped, never edited).
    segs = list(wm.transcribe(audio, vad_filter=True, vad_parameters={"threshold": 0.25, "min_silence_duration_ms": 300,
                                                                       "speech_pad_ms": 200}, **common)[0])
    transcribe_words.mode = "vad"
    if not any(s.words for s in segs):
        segs = [s for s in wm.transcribe(audio, vad_filter=False, **common)[0]
                if s.avg_logprob >= -1.0 and s.no_speech_prob <= 0.6 and s.compression_ratio <= 2.4]
        transcribe_words.mode = "no-vad fallback (guarded)"
    words, last = [], None
    for s in segs:
        if s.text.strip() == last:
            continue                      # repeated segment = typical hallucination loop
        last = s.text.strip()
        for w in (s.words or []):
            text = w.word.strip()
            if text:
                words.append({"word": text, "start": round(float(w.start), 3), "end": round(float(w.end), 3)})
    return words


def group_words(words, max_words=3, max_gap=0.5, max_len=1.6):
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w["start"] - cur[-1]["end"] > max_gap or w["end"] - cur[0]["start"] > max_len):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return groups


def _ass_time(sec):
    cs = int(round(max(sec, 0) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(word):
    return word.replace("\\", "").replace("{", "").replace("}", "")


def build_ass(words, duration, highlight=WORD_STYLES[DEFAULT_WORD_STYLE]):
    """Word-by-word reveal: each event shows the group's words so far; the current word pops in
    (130% -> 100% over 120 ms) and is highlighted. Bold white, black outline, above the bottom 15%."""
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\nScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            f"Style: Word,{CAPTION_FONT},84,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,6,2,2,80,80,"
            f"{CAPTION_MARGIN_V},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = []
    groups = group_words(words)
    for gi, g in enumerate(groups):
        g_end = min(g[-1]["end"] + 0.25, groups[gi + 1][0]["start"] if gi + 1 < len(groups) else duration, duration)
        for i, w in enumerate(g):
            start = w["start"]
            end = g[i + 1]["start"] if i + 1 < len(g) else g_end
            if end <= start:
                end = start + 0.05
            shown = " ".join(_clean(x["word"]) for x in g[:i])
            cur = (f"{{\\c{highlight}\\fscx130\\fscy130\\t(0,120,\\fscx100\\fscy100)}}{_clean(w['word'])}{{\\r}}")
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Word,,0,0,0,,{(shown + ' ') if shown else ''}{cur}")
    return head + "\n".join(lines) + ("\n" if lines else "")


def ass_words(ass_text):
    """Words shown by the final event of each caption group (for tests/review): strips override tags."""
    import re
    out = []
    events = [l.split(",", 9)[9] for l in ass_text.splitlines() if l.startswith("Dialogue:")]
    texts = [re.sub(r"\{[^}]*\}", "", e) for e in events]
    for i, t in enumerate(texts):
        nxt = texts[i + 1] if i + 1 < len(texts) else None
        if nxt is None or not nxt.startswith(t + " "):
            out += t.split()
    return out


# ---------- audio-energy spikes ----------
def energy_db(media, hop=0.1, start=None, duration=None):
    """RMS dB per hop. With start/duration it reads that window of the ORIGINAL source (before loudnorm,
    which flattens spikes), so punch-ins follow the real stream dynamics."""
    import numpy as np
    seek = ["-ss", str(start)] if start is not None else []
    dur = ["-t", str(duration)] if duration is not None else []
    p = subprocess.run(["ffmpeg", "-v", "error", *seek, "-i", str(media), *dur, "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                       capture_output=True, check=True)
    x = np.frombuffer(p.stdout, dtype="<i2").astype("float32") / 32768.0
    n = int(8000 * hop)
    frames = x[: len(x) // n * n].reshape(-1, n) if len(x) >= n else x.reshape(1, -1)
    return [float(v) for v in 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)]


def spikes(db, hop=0.1, duration=None, min_gap=MIN_GAP, rise_db=4.5, baseline_s=3.0):
    """Punch-in times: energy rising >= rise_db (4.5 dB) above the median of the previous 3 s, local maxima, strongest first,
    never closer than min_gap seconds (so at most one per 4 s). Skips the hook (first 0.7 s) and the tail."""
    import numpy as np
    db = np.asarray(db, dtype="float32")
    if db.size == 0:
        return []
    duration = duration or db.size * hop
    look = max(1, int(baseline_s / hop))   # trailing baseline: the 3 s BEFORE each point
    base = np.array([np.median(db[max(0, i - look): i]) if i else db[0] for i in range(db.size)])
    excess = db - base
    floor = np.percentile(db, 60)
    cands = []
    for i in range(1, db.size - 1):
        t = i * hop
        if excess[i] >= rise_db and db[i] >= floor and db[i] >= db[i - 1] and db[i] >= db[i + 1] \
                and HOOK_SECONDS + 0.2 <= t <= duration - (EASE * 2 + HOLD + FADE_SECONDS):
            cands.append((float(excess[i]), round(t, 2)))
    picked = []
    for ex, t in sorted(cands, reverse=True):
        if all(abs(t - p["t"]) >= min_gap for p in picked):
            picked.append({"t": t, "excess_db": round(ex, 1)})
    picked.sort(key=lambda p: p["t"])
    top = sorted(picked, key=lambda p: p["excess_db"], reverse=True)[: (2 if len(picked) >= 4 else 1)]
    for p in picked:
        p["shake"] = p in top
    return picked


# ---------- filter graph ----------
def _smooth(x):
    return f"(({x})*({x})*(3-2*({x})))"


def zoom_expr(punches, hook=True):
    T = f"(on/{FPS})"
    terms = []
    if hook:
        a = f"clip({T}/{HOOK_SECONDS},0,1)"
        terms.append(f"{HOOK_ZOOM - 1:.3f}*(1-{_smooth(a)})")
    for p in punches:
        t0 = p["t"] - 0.1
        a = f"clip(({T}-{t0:.3f})/{EASE},0,1)"
        b = f"clip(({T}-{t0 + EASE + HOLD:.3f})/{EASE},0,1)"
        terms.append(f"{ZOOM - 1:.3f}*({_smooth(a)}-{_smooth(b)})")
    return "1+" + "+".join(terms) if terms else "1"


def shake_expr(punches, axis):
    T = f"(on/{FPS})"
    fn = "sin" if axis == "x" else "cos"
    parts = [f"{SHAKE_PX}*{fn}({T}*94)*between({T},{p['t']:.3f},{p['t'] + SHAKE_SECONDS:.3f})" for p in punches if p.get("shake")]
    return "+".join(parts) if parts else "0"


def video_graph(style, duration, punches=(), ass_name=None, joins=(), flash=False):
    """[0:v] -> [v]. Captions are drawn after the zoom so they stay steady."""
    if ass_name is not None and not all(c.isalnum() or c in "._-" for c in ass_name):
        raise ValueError("unsafe subtitle file name")
    chain = [f"fps={FPS}"]
    if style == "hype":
        z = zoom_expr(punches)
        sx, sy = shake_expr(punches, "x"), shake_expr(punches, "y")
        chain.append(f"zoompan=z='{z}':x='clip(iw/2-iw/zoom/2+{sx},0,iw-iw/zoom)':y='clip(ih/2-ih/zoom/2+{sy},0,ih-ih/zoom)'"
                     f":d=1:s={W}x{H}:fps={FPS}")
        chain.append("setpts=PTS-STARTPTS")
        if flash:
            for j in joins:
                chain.append(f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t=fill:enable='between(t,{j - 0.04:.3f},{j + 0.12:.3f})'")
    chain.append("setsar=1")
    if ass_name:
        chain.append(f"ass={ass_name}")
    if style == "hype":
        chain.append(f"drawbox=x=0:y=ih-{BAR_PX}:w='iw*min(t/{duration:.3f},1)':h={BAR_PX}:color=white@0.9:t=fill")
        chain.append(f"fade=t=out:st={max(duration - FADE_SECONDS, 0):.3f}:d={FADE_SECONDS}")
    return "[0:v]" + ",".join(chain) + "[v]"


def duration_of(media):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(media)],
                       capture_output=True, text=True, check=True)
    return float(json.loads(p.stdout)["format"]["duration"])


def apply(path, style, joins=(), flash=False, word_style=None, model=None, energy_source=None):
    """Edit `path` in place (tmp + os.replace). Audio stream copied unchanged. Returns a render-record dict."""
    path = pathlib.Path(path)
    if style == "off":
        return {"edit_style": "off"}
    t0 = time.monotonic()
    duration = duration_of(path)
    word_style = word_style if word_style in WORD_STYLES else DEFAULT_WORD_STYLE
    words = transcribe_words(path, model)
    ass_name = None
    if words:
        ass_name = path.stem + ".words.ass"
        (path.parent / ass_name).write_text(build_ass(words, duration, WORD_STYLES[word_style]))
        (path.parent / (path.stem + ".words.json")).write_text(json.dumps(words, indent=1))
    if style == "hype":
        src, s0 = (energy_source[0], energy_source[1]) if energy_source else (path, None)
        punches = spikes(energy_db(src, start=s0, duration=duration if energy_source else None), duration=duration)
    else:
        punches = []
    graph = video_graph(style, duration, punches, ass_name, joins, flash)
    tmp = path.with_name(path.stem + ".edit.tmp.mp4")
    try:
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path.name, "-filter_complex", graph,
                        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                        "-r", str(FPS), "-c:a", "copy", "-movflags", "+faststart", tmp.name], check=True, cwd=str(path.parent))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    rec = {"edit_style": style, "edit_seconds": round(time.monotonic() - t0, 1),
           "word_captions": ("BURNED_WORD_BY_WORD_NEEDS_HUMAN_CHECK" if words else
                             ("SKIPPED_NO_FASTER_WHISPER" if words is None else "SKIPPED_NO_SPEECH")),
           "word_caption_style": word_style if words else None, "word_count": len(words or []),
           "transcribe_mode": (lambda m: m if isinstance(m, str) and words is not None else None)(getattr(transcribe_words, "mode", None)),
           "edit_audio": "copied unchanged (-c:a copy)"}
    if style == "hype":
        rec.update({"spike_source": "original source audio (pre-loudnorm)" if energy_source else "rendered audio",
                    "punch_ins": [p["t"] for p in punches], "zoom_count": len(punches),
                    "shake_at": [p["t"] for p in punches if p["shake"]], "hook_zoom": f"{HOOK_ZOOM}->1.0 over {HOOK_SECONDS}s",
                    "end_fade": f"{FADE_SECONDS}s", "progress_bar": True,
                    "flash_cuts": [round(j, 3) for j in joins] if flash else []})
    return rec
