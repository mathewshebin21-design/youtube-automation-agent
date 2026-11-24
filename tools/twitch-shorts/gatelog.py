"""Signed human review log (HMAC hash chain) and the per-upload audit ledger (daily cap + duplicates).

The signing key lives only in your environment (CUTSCENECITY_REVIEW_KEY, 32+ characters).
It is never written to disk by this code, never printed, and never sent anywhere.
"""
import datetime as dt
import hashlib
import hmac
import json
import os
import pathlib
import re

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
BLOCKING_UPLOAD_STATES = {"ATTEMPT", "UPLOADED", "UNKNOWN_RECONCILE"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _key():
    key = os.getenv("CUTSCENECITY_REVIEW_KEY", "")
    if len(key) < 32:
        raise PermissionError("set CUTSCENECITY_REVIEW_KEY (32+ random characters) in your shell or .env; it signs the review log")
    return key.encode()


def _sign(entry):
    body = {k: v for k, v in entry.items() if k != "sig"}
    return hmac.new(_key(), json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()


def append_review(log_path, **fields):
    log_path = pathlib.Path(log_path)
    entries = verify_review_log(log_path) if log_path.exists() else []
    entry = {"seq": len(entries) + 1, "at": dt.datetime.now(IST).isoformat(timespec="seconds"),
             "prev": entries[-1]["sig"] if entries else "GENESIS", **fields}
    entry["sig"] = _sign(entry)
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def verify_review_log(log_path):
    entries, prev = [], "GENESIS"
    for n, line in enumerate(pathlib.Path(log_path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("seq") != n or e.get("prev") != prev or not hmac.compare_digest(e.get("sig", ""), _sign(e)):
            raise PermissionError(f"review log tampered or signed with another key at line {n}")
        entries.append(e)
        prev = e["sig"]
    return entries


def latest_approval(entries, clip_file):
    approvals = [e for e in entries if e.get("action") == "approve" and e.get("clip") == clip_file]
    return approvals[-1] if approvals else None


# ---------- upload audit ledger ----------
def state_dir():
    d = pathlib.Path(os.getenv("CUTSCENECITY_STATE_DIR", str(pathlib.Path.home() / ".cutscenecity")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_path():
    return state_dir() / "upload-audit.jsonl"


def read_ledger():
    p = ledger_path()
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def audit(**fields):
    entry = {"at": dt.datetime.now(IST).isoformat(timespec="seconds"), **fields}
    with open(ledger_path(), "a") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def vod_id(url):
    m = re.search(r"/videos/(\d+)", url or "")
    return m.group(1) if m else None


def _final_states(entries):
    """Latest state per package (an ATTEMPT followed by FAILED no longer counts as a duplicate)."""
    state = {}
    for e in entries:
        state[e["package_sha256"]] = e
    return state.values()


HARD_DAILY_CAP = 1  # phase 2.7 (Compliance): back from 2 to 1; day boundary = IST (UTC+05:30)


def effective_daily_cap(env_value=None, policy_value=None):
    """min(env or policy, 2). Nothing can raise it above 2; 0, negative or unparseable means blocked."""
    raw = env_value if env_value not in (None, "") else policy_value
    if raw is None:
        raw = HARD_DAILY_CAP
    if isinstance(raw, bool) or not re.fullmatch(r"\s*-?\d+\s*", str(raw)):
        return 0
    return max(0, min(int(str(raw).strip()), HARD_DAILY_CAP))


def upload_blockers(package, cap, today=None):
    today = today or dt.datetime.now(IST).date().isoformat()
    entries = read_ledger()
    out = []
    cap = min(int(cap), HARD_DAILY_CAP) if isinstance(cap, int) and not isinstance(cap, bool) else 0
    if cap <= 0:
        out.append("daily cap is 0 or invalid: uploads are disabled (fail closed)")
    attempts_today = [e for e in entries if e.get("status") == "ATTEMPT" and e["at"][:10] == today]
    if len(attempts_today) >= cap:
        out.append(f"daily cap reached: {len(attempts_today)}/{cap} upload attempts today (IST)")
    src = package["source"]
    for e in _final_states(entries):
        if e.get("status") not in BLOCKING_UPLOAD_STATES:
            continue
        if e.get("status") == "UNKNOWN_RECONCILE" and e["package_sha256"] == package["package_sha256"]:
            out.append("previous attempt ended without a clear result: check YouTube Studio, then run upload_private.py reconcile")
        elif e.get("file_sha256") == package["file_sha256"] or e["package_sha256"] == package["package_sha256"]:
            out.append(f"duplicate: this file was already sent ({e.get('status')}, video {e.get('video_id')})")
        elif e.get("vod_id") == src["vod_id"] and e.get("start_ms", 0) < src["end_ms"] and src["start_ms"] < e.get("end_ms", 0):
            out.append(f"duplicate: overlaps VOD {src['vod_id']} {e['start_ms'] / 1000:.1f}-{e['end_ms'] / 1000:.1f}s already sent")
    return out
