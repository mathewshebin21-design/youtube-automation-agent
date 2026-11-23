"""Commentary-script reuse checks (gate 4b) and voice/caption rotation (gate 4c).

Similarity: 3-word shingle Jaccard against the last 30 approved/uploaded scripts.
  >= 0.40 -> WARN (reviewer must write a note), > 0.50 -> FAIL.
Opener/CTA: first and last sentence may not repeat (exact, or word-set Jaccard >= 0.8) any recent one.
The Node ingest route re-implements the same rules (utils/cutscenecity/external-shorts.js).
"""
import json
import re

import gatelog

FLAG_AT, REJECT_ABOVE, NEAR_LINE, HISTORY_N, SHINGLE = 0.40, 0.50, 0.80, 30, 3
_WORD = re.compile(r"[^\w\s']", re.UNICODE)
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def words(text):
    return _WORD.sub(" ", str(text or "").lower()).split()


def shingles(text, n=SHINGLE):
    w = words(text)
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))} if len(w) >= n else ({" ".join(w)} if w else set())


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def sentences(text):
    return [s.strip() for s in _SENT.split(str(text or "").strip()) if s.strip()]


def opener_cta(text):
    s = sentences(text)
    return (s[0], s[-1]) if s else ("", "")


def near_line(a, b):
    wa, wb = set(words(a)), set(words(b))
    return bool(wa and wb) and (" ".join(words(a)) == " ".join(words(b)) or jaccard(wa, wb) >= NEAR_LINE)


def history_path():
    return gatelog.state_dir() / "script-history.jsonl"


def read_history():
    p = history_path()
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
    latest = {}
    for r in rows:  # one row per clip_key, latest wins
        latest[r["clip_key"]] = r
    return list(latest.values())[-HISTORY_N:]


def record(clip_key, text, voice_preset, caption_style):
    with open(history_path(), "a") as f:
        f.write(json.dumps({"clip_key": clip_key, "script": text, "voice_preset": voice_preset,
                            "caption_style": caption_style}, sort_keys=True) + "\n")


def clip_key(clip):
    p = clip.get("provenance") or {}
    return gatelog.sha256_json({"url": p.get("source_url", ""), "start_ms": int(round(float(clip["start"]) * 1000)),
                                "end_ms": int(round(float(clip["end"]) * 1000))})


def check_script(text, history, own_key):
    """Returns (status, evidence, max_similarity)."""
    sh = shingles(text)
    op, cta = opener_cta(text)
    worst, problems = 0.0, []
    for h in history:
        if h.get("clip_key") == own_key:
            continue
        sim = jaccard(sh, shingles(h.get("script", "")))
        worst = max(worst, sim)
        hop, hcta = opener_cta(h.get("script", ""))
        if near_line(op, hop):
            problems.append(f"reused opener: '{op[:60]}'")
        if near_line(cta, hcta):
            problems.append(f"reused CTA/closing line: '{cta[:60]}'")
    if worst > REJECT_ABOVE:
        problems.append(f"script overlaps a recent script by {worst:.0%} (> {REJECT_ABOVE:.0%})")
    if problems:
        return "FAIL", "; ".join(sorted(set(problems))), worst
    if worst >= FLAG_AT:
        return "WARN", f"script overlaps a recent script by {worst:.0%} (flag at {FLAG_AT:.0%})", worst
    return "PASS", f"max overlap {worst:.0%} vs {len(history)} recent scripts", worst


def previous_upload(exclude_package=None):
    """Latest ATTEMPT/UPLOADED ledger entry of another package (its voice preset and caption style must not repeat)."""
    for e in reversed(gatelog.read_ledger()):
        if e.get("status") in ("ATTEMPT", "UPLOADED") and e.get("package_sha256") != exclude_package:
            return e
    return None
