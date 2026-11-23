"""Candidate-selection signals: motion (from pipeline), audio loudness, chat velocity, transcript keywords.

Every signal is optional except motion. Missing signals are dropped and the remaining
weights are renormalised, and the selection notes say which signals were actually used.
These are heuristics: they rank windows for a HUMAN to review, they do not understand gameplay.
"""
import json
import pathlib
import subprocess

import numpy as np

DEFAULT_WEIGHTS = {"motion": 0.35, "audio": 0.35, "chat": 0.2, "keywords": 0.1}
DEFAULT_KEYWORDS = ["no way", "oh my god", "let's go", "what", "bro", "run", "help", "crazy", "insane", "clip that"]


def audio_loudness(video, rate=8000):
    """Per-second RMS loudness in dBFS from the first audio stream. Returns [] if no audio."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return []
    pcm = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    out = []
    for i in range(len(pcm) // rate):
        chunk = pcm[i * rate:(i + 1) * rate]
        rms = float(np.sqrt(np.mean(chunk * chunk))) or 1e-9
        out.append((float(i), 20 * np.log10(rms)))
    return out


def chat_times(path):
    """Message offsets (seconds) from a chat export.

    Accepts TwitchDownloader JSON ({"comments":[{"content_offset_seconds":..}]}),
    yt-dlp live_chat-style lists, or a plain list of {"t": seconds} / numbers.
    """
    data = json.loads(pathlib.Path(path).read_text())
    items = data.get("comments", data) if isinstance(data, dict) else data
    times = []
    for item in items:
        if isinstance(item, (int, float)):
            times.append(float(item))
        elif isinstance(item, dict):
            for key in ("content_offset_seconds", "t", "offset", "time"):
                if key in item:
                    times.append(float(item[key]))
                    break
    return sorted(times)


def transcript_segments(path):
    """[{start,end,text}] from a JSON transcript (faster-whisper/whisperX style or {"segments": [...]})."""
    data = json.loads(pathlib.Path(path).read_text())
    segs = data.get("segments", data) if isinstance(data, dict) else data
    return [{"start": float(s["start"]), "end": float(s["end"]), "text": str(s.get("text", ""))} for s in segs]


def _window_values(series, start, end):
    return [v for t, v in series if start <= t < end]


def _rank(values):
    """Percentile rank 0..1 so signals with different units are comparable."""
    arr = np.asarray(values, dtype=float)
    if arr.size == 0 or np.all(arr == arr[0]):
        return np.zeros_like(arr)
    order = arr.argsort().argsort()
    return order / (arr.size - 1)


def score_windows(duration, motion, audio=None, chat=None, transcript=None, seconds=35, step=None,
                  weights=None, keywords=None):
    """Score fixed windows on every available signal; returns a list of dicts with raw values and notes."""
    weights = dict(weights or DEFAULT_WEIGHTS)
    keywords = [k.lower() for k in (keywords or DEFAULT_KEYWORDS)]
    step = step or max(8, seconds // 2)
    starts = list(np.arange(0, max(1, duration - seconds), step)) or [0.0]
    rows = []
    for start in starts:
        start = float(start)
        end = float(min(duration, start + seconds))
        m = _window_values(motion, start, end)
        if not m:
            continue
        row = {"start": round(start, 2), "end": round(end, 2), "raw": {"motion_p75": float(np.percentile(m, 75))}, "evidence": []}
        if audio:
            pairs = [(t, v) for t, v in audio if start <= t < end]
            a = [v for _, v in pairs]
            if a:
                peak_t = max(pairs, key=lambda p: p[1])[0]
                row["raw"]["audio_peak_dbfs"] = float(max(a))
                row["raw"]["audio_p90_dbfs"] = float(np.percentile(a, 90))
                row["evidence"].append(f"loudest second at {peak_t:.0f}s ({max(a):.1f} dBFS)")
        if chat is not None:
            n = sum(1 for t in chat if start <= t < end)
            row["raw"]["chat_msgs_per_min"] = n * 60.0 / max(1.0, end - start)
            if n:
                row["evidence"].append(f"{n} chat messages in window")
        if transcript is not None:
            hits = []
            for s in transcript:
                if s["end"] > start and s["start"] < end:
                    text = s["text"].lower()
                    hits += [f"'{k}' @{s['start']:.0f}s" for k in keywords if k in text]
            row["raw"]["keyword_hits"] = len(hits)
            if hits:
                row["evidence"].append("transcript keywords: " + ", ".join(hits[:5]))
        rows.append(row)
    if not rows:
        return []
    used = {"motion": "motion_p75"}
    if audio:
        used["audio"] = "audio_p90_dbfs"
    if chat is not None:
        used["chat"] = "chat_msgs_per_min"
    if transcript is not None:
        used["keywords"] = "keyword_hits"
    total = sum(weights.get(k, 0) for k in used) or 1.0
    for sig, key in used.items():
        ranks = _rank([r["raw"].get(key, 0.0) for r in rows])
        for r, rank in zip(rows, ranks):
            r.setdefault("signal_ranks", {})[sig] = round(float(rank), 3)
    for r in rows:
        r["combined_score"] = round(100 * sum(weights.get(s, 0) * r["signal_ranks"][s] for s in used) / total, 1)
        r["signals_used"] = sorted(used)
    return rows


def select(rows, limit=6, min_score=0.0):
    """Highest combined score first, no overlapping windows, 0..limit results (not a quota)."""
    selected = []
    for r in sorted(rows, key=lambda r: r["combined_score"], reverse=True):
        if r["combined_score"] < min_score:
            break
        if all(r["end"] <= s["start"] or r["start"] >= s["end"] for s in selected):
            selected.append(r)
        if len(selected) == limit:
            break
    for rank, r in enumerate(selected, 1):
        top = sorted(r["signal_ranks"].items(), key=lambda kv: kv[1], reverse=True)
        r["selection_note"] = (
            f"Rank {rank}: combined {r['combined_score']}/100 from {', '.join(r['signals_used'])}. "
            f"Strongest signal: {top[0][0]} (percentile {top[0][1]:.2f}). "
            + ("; ".join(r["evidence"]) + ". " if r["evidence"] else "")
            + "Heuristic only: a human must confirm setup, payoff and that this is not a story cutscene."
        )
    return selected
