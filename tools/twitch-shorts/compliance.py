"""Pluggable, default-deny compliance gates for each review candidate.

Every registered check starts BLOCKING (status PENDING). A clip can only be approved,
exported or uploaded when every check is PASS. Two kinds of check:

  auto   - evaluated from the manifest/media (e.g. provenance, commentary coverage, spoilers).
           Code can set PASS or FAIL; nothing else can override an auto FAIL.
  human  - only a named person can mark PASS (review.py signoff). An optional auto "hint"
           runs first; a FAIL hint blocks the sign-off, a WARN hint needs a written note.

Add a gate:

    from compliance import register_check
    @register_check("my_gate", kind="human", description="...")
    def my_gate_hint(clip, ctx):            # optional; return ("PASS"|"WARN"|"FAIL", "evidence")
        return "WARN", "needs eyes"

or list it in editorial-policy.json under "extra_human_checks": [{"name": ..., "description": ...}].
"""
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess

CHECKS = {}
PASS, FAIL, WARN, PENDING = "PASS", "FAIL", "WARN", "PENDING"
TWITCH_VOD = re.compile(r"^https://(?:www\.)?twitch\.tv/videos/\d+$")
TWITCH_VOD_ID = re.compile(r"^https://(?:www\.)?twitch\.tv/videos/(\d+)$")
DEFAULT_SPOILERS = json.loads((pathlib.Path(__file__).parent / "spoiler-defaults.json").read_text())["terms"]


def register_check(name, kind="auto", description="", applies=None):
    """applies(clip) -> bool: a human check that does not apply to this clip is recorded as PASS/not_applicable
    and needs no signature (e.g. mixed_track_commentary_confirmed when a mic stem exists)."""
    if kind not in ("auto", "human"):
        raise ValueError("kind must be auto or human")

    def deco(fn):
        CHECKS[name] = {"kind": kind, "description": description, "fn": fn, "applies": applies}
        return fn
    if name in CHECKS:
        raise ValueError(f"check {name} already registered")
    CHECKS[name] = {"kind": kind, "description": description, "fn": None, "applies": applies}
    return deco


def applies(name, clip):
    fn = CHECKS[name].get("applies")
    return True if fn is None else bool(fn(clip))


def required_human_checks(clip):
    return [n for n, s in CHECKS.items() if s["kind"] == "human" and applies(n, clip)]


def load_extra_checks(policy):
    for item in (policy or {}).get("extra_human_checks", []):
        if item["name"] not in CHECKS:
            register_check(item["name"], "human", item.get("description", ""))


# ---------- gate 1: creator-owned source ----------
OWNER_LOGIN_ENV, OWNER_ID_ENV = "CUTSCENECITY_OWNER_TWITCH_LOGIN", "CUTSCENECITY_OWNER_TWITCH_ID"


def policy_owner_login(policy=None):
    """Owner login from editorial-policy.json (`owner_twitch_login`; a public login, not a secret)."""
    if policy is None:
        try:
            policy = json.loads((pathlib.Path(__file__).parent / "editorial-policy.json").read_text())
        except (OSError, ValueError):
            return ""
    return str((policy or {}).get("owner_twitch_login") or "").strip()


def owner_match(meta, env=None, default_login=None):
    """Does yt-dlp metadata prove the VOD belongs to the configured owner? Fail closed on anything unknown.

    meta: {"uploader", "uploader_id", "channel", "channel_id"} as reported by `yt-dlp -J`.
    For Twitch VODs yt-dlp reports uploader (display name) and uploader_id (login); numeric
    channel_id is usually absent, so configure the LOGIN.
    Owner login = env CUTSCENECITY_OWNER_TWITCH_LOGIN if set and non-empty, else the policy's
    owner_twitch_login (default_login; None = read editorial-policy.json). Both empty -> FAIL.
    """
    env = os.environ if env is None else env
    if default_login is None:
        default_login = policy_owner_login()
    login = (str(env.get(OWNER_LOGIN_ENV, "")).strip() or str(default_login or "").strip()).lower()
    oid = str(env.get(OWNER_ID_ENV, "")).strip()
    if not login and not oid:
        return FAIL, f"owner not configured: set {OWNER_LOGIN_ENV} or owner_twitch_login in editorial-policy.json"
    meta = meta or {}
    low = {k: str(meta.get(k) or "").strip().lower() for k in ("uploader", "uploader_id", "channel")}
    cid = str(meta.get("channel_id") or "").strip()
    if not any(low.values()) and not cid:
        return FAIL, "VOD channel unknown: no uploader/uploader_id/channel/channel_id in yt-dlp metadata"
    if login and low["uploader_id"] and low["uploader_id"] != login:
        return FAIL, f"VOD uploader_id '{low['uploader_id']}' is not the owner login"
    if oid and cid and cid != oid:
        return FAIL, f"VOD channel_id '{cid}' is not the owner id"
    if login and low["channel"] and low["channel"] != login:
        return FAIL, f"VOD channel '{low['channel']}' is not the owner login"
    # uploader (display name) is recorded as evidence but never enough on its own
    if login and login in (low["uploader_id"], low["channel"]):
        return PASS, f"VOD login '{login}' matches owner"
    if oid and cid == oid:
        return PASS, f"VOD channel_id {oid} matches owner"
    return FAIL, "could not confirm the VOD owner from metadata (owner login/id not reported)"


@register_check("creator_owned_source", "auto",
                "Source VOD belongs to the configured owner channel (yt-dlp metadata vs "
                "CUTSCENECITY_OWNER_TWITCH_LOGIN / CUTSCENECITY_OWNER_TWITCH_ID). No third-party sources.")
def creator_owned_source(clip, ctx):
    p = clip.get("provenance") or {}
    m = TWITCH_VOD_ID.match(p.get("source_url") or "")
    if not m:
        return FAIL, "source_url is not a Twitch VOD URL"
    meta = p.get("source_owner") or {}
    if str(meta.get("vod_id") or "") != m.group(1):
        return FAIL, "yt-dlp metadata missing or for a different VOD id"
    pol = ctx.get("policy")
    return owner_match(meta, ctx.get("env"), policy_owner_login(pol) if pol is not None else None)


@register_check("vod_rights_confirmed", "human",
                "A person confirms the VOD is from their own channel and the provenance record is true.")
def vod_rights_hint(clip, ctx):
    status, why = creator_owned_source(clip, ctx)
    return (PASS, why) if status == PASS else (FAIL, "creator_owned_source must pass first: " + why)


# ---------- gate 2: cutscene detection ----------
def letterbox_ratio(video, start, end, samples=10):
    """Share of sampled frames whose top and bottom 9% bands are near-black (typical cinematic letterbox)."""
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(str(video))
    hits = seen = 0
    for i in range(samples):
        cap.set(cv2.CAP_PROP_POS_MSEC, 1000 * (start + (end - start) * (i + 0.5) / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        seen += 1
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        band = max(1, int(g.shape[0] * 0.09))
        if g[:band].mean() < 14 and g[-band:].mean() < 14 and g[band:-band].mean() > 20:
            hits += 1
    cap.release()
    return hits / seen if seen else None


@register_check("no_story_cutscene", "human",
                "A person confirms the clip is player gameplay, not a story cutscene (Rockstar story content).")
def cutscene_hint(clip, ctx):
    r = clip.get("cutscene_scan", {}).get("letterbox_ratio")
    if r is None:
        return WARN, "cutscene scan not run; reviewer must check the whole clip"
    if r >= 0.3:
        return WARN, f"letterbox bars in {r:.0%} of sampled frames: likely cutscene"
    return PASS, f"letterbox bars in {r:.0%} of sampled frames (heuristic only)"


# ---------- gate 3: music / radio ----------
def fingerprint(path):
    """Chromaprint pre-check hook. Computes a fingerprint with `fpcalc` if installed.

    Matching (AcoustID lookup, or YouTube's own Content ID after a private upload) is NOT done here:
    the result is evidence for the human music_risk_cleared sign-off, never an automatic PASS.
    """
    if not shutil.which("fpcalc"):
        return {"tool": "chromaprint/fpcalc", "status": "NOT_INSTALLED"}
    p = subprocess.run(["fpcalc", "-json", "-length", "120", str(path)], capture_output=True, text=True)
    if p.returncode != 0:
        return {"tool": "chromaprint/fpcalc", "status": "ERROR"}
    data = json.loads(p.stdout)
    return {"tool": "chromaprint/fpcalc", "status": "COMPUTED_NOT_MATCHED",
            "duration": data.get("duration"), "fingerprint_prefix": str(data.get("fingerprint", ""))[:32]}


@register_check("music_risk_cleared", "human",
                "Game audio is kept by default (mix, music volume adjustable); a person listens for licensed "
                "music/radio (Content ID risk) and signs off; fingerprint pre-check result attached.")
def music_hint(clip, ctx):
    render = clip.get("render") or {}
    fp = clip.get("fingerprint_precheck")
    if not fp:
        return FAIL, "run the fingerprint pre-check (review.py precheck) before signing off"
    if render.get("audio_mode") != "mic_stem":
        return WARN, (f"original game audio kept (music volume {render.get('music_volume', 1.0)}); licensed in-game radio "
                      f"may trigger Content ID: listen to the whole clip, fingerprint {fp.get('status')}; note required")
    return WARN, f"game/music audio dropped; fingerprint {fp.get('status')}: listen for music picked up by the mic"


# ---------- third-party overlays (chat, alerts, usernames, viewer TTS, guest audio) ----------
@register_check("overlays_third_parties_cleared", "human",
                "A person confirms chat, alert and username regions are blurred in the FINAL render, no viewer "
                "TTS/donation messages are audible, and no guest or voice-chat audio is in the mix.")
def overlay_hint(clip, ctx):
    s = clip.get("overlay_scan")
    if not s:
        return FAIL, "run the overlay scan on the final render (review.py precheck) before signing off"
    if s.get("flagged") is None:
        return WARN, "overlay scan unavailable (" + str(s.get("error", "no detector")) + "): check every frame, note required"
    if s["flagged"]:
        return WARN, (f"possible text/overlay in {len(s.get('regions') or [])} region(s) via {'+'.join(s.get('methods', []))}: "
                      "confirm each is blurred or is your own HUD, note required")
    return PASS, "no persistent overlay text detected (heuristic; human check still required)"


# ---------- paid promotion (videos.insert paidProductPlacementDetails) ----------
PAID_VALUES = ("none", "present")


@register_check("paid_promotion_declared", "auto",
                "Reviewer declared paid_promotion as none or present (signed); sent explicitly on upload.")
def paid_gate(clip, ctx):
    v = (clip.get("paid_promotion") or {}).get("value")
    if v not in PAID_VALUES:
        return FAIL, "paid_promotion missing: run review.py paid --value none|present --by NAME"
    return PASS, f"paid_promotion={v} (hasPaidProductPlacement={v == 'present'})"


# ---------- gate 4 (v3): commentary >= 60%, live reaction kept, script, reuse, rotation ----------
def speech_seconds(audio_path, noise_db=-35, min_silence=0.4):
    """Seconds of non-silence in a commentary track, via ffmpeg silencedetect."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(audio_path), "-af",
                        f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
                       capture_output=True, text=True)
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    if not dur:
        raise ValueError("could not read commentary duration")
    total = int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3))
    silent = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", p.stderr))
    return max(0.0, total - silent)


def mixed_speech_share(media, start=None, end=None):
    """HINT ONLY: share of the clip where the mixed VOD track has voice-band energy (300-3400 Hz energy VAD).
    Game voices, cutscene dialogue and music count as speech too, so this can never pass a gate on its own."""
    args = ["ffmpeg", "-hide_banner"]
    if start is not None:
        args += ["-ss", str(start), "-t", str(float(end) - float(start))]
    args += ["-i", str(media), "-vn", "-af", "highpass=f=300,lowpass=f=3400,silencedetect=noise=-30dB:d=0.3", "-f", "null", "-"]
    p = subprocess.run(args, capture_output=True, text=True)
    dur = (float(end) - float(start)) if start is not None else None
    if dur is None:
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
        if not m:
            return None
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    if p.returncode != 0 or dur <= 0:
        return None
    silent = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", p.stderr))
    return round(max(0.0, min(1.0, (dur - silent) / dur)), 3)


def is_mixed_track(clip):
    """No separate creator mic stem: commentary is only in the single mixed VOD track."""
    return not (clip.get("commentary") or {}).get("mic_source") and not (clip.get("render") or {}).get("mic_source")


def mixed_track_signed(clip):
    return (is_mixed_track(clip) and owner_ok(clip)
            and (clip.get("compliance") or {}).get("mixed_track_commentary_confirmed", {}).get("status") == PASS
            and not clip["compliance"]["mixed_track_commentary_confirmed"].get("not_applicable"))


def owner_ok(clip):
    return creator_owned_source(clip, {"policy": None})[0] == PASS


@register_check("mixed_track_commentary_confirmed", "human",
                "Mixed-track path (no mic stem; Twitch VOD has one mixed track): a person listened to the whole clip and "
                "confirms the creator's live commentary is clearly audible over the game audio. Note of 5+ words required.",
                applies=is_mixed_track)
def mixed_track_hint(clip, ctx):
    if not owner_ok(clip):
        return FAIL, "mixed-track path is only for creator-owned VODs (creator_owned_source must pass)"
    share = (clip.get("commentary") or {}).get("mixed_track_speech_share")
    if share is None:
        return WARN, "no speech hint yet (review.py precheck); listen to the whole clip; note required"
    return WARN, (f"voice-band activity in {share:.0%} of the clip (hint only: game voices/music count too); "
                  "confirm YOUR live commentary is audible; note required")


def tts_counts(env=None):
    env = os.environ if env is None else env
    return str(env.get("CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY", "true")).strip().lower() not in ("false", "0", "no", "off")


@register_check("original_commentary", "auto",
                "Creator mic + voiceover/TTS (energy VAD on the combined commentary bus) covers at least 60% of runtime. "
                "TTS counts only when CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY is on (default) and containsSyntheticMedia is true.")
def commentary_gate(clip, ctx):
    c = clip.get("commentary") or {}
    if not c.get("mic_source"):
        if not owner_ok(clip):
            return FAIL, "no creator mic stem and the VOD is not creator-owned"
        if mixed_track_signed(clip):
            return PASS, "mixed_track_signed: reviewer confirmed live commentary is audible (no mic stem to measure)"
        share = c.get("mixed_track_speech_share")
        hint = f"; voice-band hint {share:.0%} (game voices count too)" if share is not None else ""
        return WARN, ("no mic stem: commentary cannot be measured on the single mixed track" + hint +
                      ". Sign mixed_track_commentary_confirmed, or attach an OBS mic track (review.py commentary --mic-stream N)")
    if c.get("tts_used") and (clip.get("metadata") or {}).get("containsSyntheticMedia") is not True:
        return FAIL, "TTS used: containsSyntheticMedia must be true"
    runtime = float(clip["end"]) - float(clip["start"])
    counts = tts_counts(ctx.get("env"))
    speech = float(c.get("speech_seconds_combined" if counts else "speech_seconds_live", 0) or 0)
    cov = speech / runtime if runtime > 0 else 0
    label = "live voice + TTS" if counts else "live voice only (TTS not counted)"
    if cov < ctx.get("min_commentary", 0.60):
        return FAIL, f"{label} covers {cov:.0%} of runtime; 60% required"
    return PASS, f"{label} covers {cov:.0%} of runtime"


@register_check("live_reaction_preserved", "auto",
                "The creator's real mic/reaction track is in the final mix at full level (never muted or ducked).")
def live_reaction_gate(clip, ctx):
    r = clip.get("render") or {}
    if is_mixed_track(clip) and r.get("audio_mode", "source") == "source" and owner_ok(clip):
        if r.get("music_volume", 1.0) != 1.0:
            return FAIL, "mixed track was lowered (music volume < 1.0 also lowers the creator voice in a mixed track)"
        if mixed_track_signed(clip):
            return PASS, "mixed_track_signed: original mixed track (creator voice included) kept at full level"
        return WARN, "single mixed VOD track kept at full level; sign mixed_track_commentary_confirmed (voice audible)"
    if r.get("audio_mode") not in ("mix", "mic_stem") or not r.get("mic_source"):
        return FAIL, ("no separate creator mic stem in the final mix; Twitch VODs have one mixed track, so the mic "
                      "cannot be separated: record an OBS multitrack (mic on its own track) and pass --mic-stream/--mic")
    if r.get("mic_gain") != 1.0:
        return FAIL, "creator mic was lowered"
    return PASS, f"creator mic {r['mic_source']} kept at full level"


@register_check("commentary_script", "auto",
                "When TTS is used: a human-edited script is stored and approved in the signed review log (review.py script).")
def script_gate(clip, ctx):
    tts = bool((clip.get("commentary") or {}).get("tts_used"))
    s = clip.get("commentary_script") or {}
    text = s.get("text") or ""
    if not text:
        return (FAIL, "TTS used: a human-edited script is required (review.py script --file ...)") if tts else (PASS, "no TTS; script optional")
    if len(text.split()) < 20:
        return FAIL, "script must be at least 20 words"
    if s.get("approved_sha256") != _sha(text):
        return FAIL, "script changed after approval or never approved (review.py script)"
    return PASS, f"script approved by {s.get('approved_by')}"


@register_check("script_originality", "auto",
                "Script vs the last 30 approved/uploaded scripts: flag at 40% shingle overlap (needs a reviewer note), "
                "reject above 50%; any reused opener or CTA line is rejected.")
def script_originality_gate(clip, ctx):
    import script_checks
    s = clip.get("commentary_script") or {}
    if not s.get("text"):
        return PASS, "no script"
    status, why, _ = script_checks.check_script(s["text"], ctx.get("script_history", []), script_checks.clip_key(clip))
    if status == WARN:
        note = s.get("similarity_note") or ""
        return (PASS, why + "; reviewer note: " + note) if len(note.split()) >= 5 else (FAIL, why + "; add a reviewer note (review.py script --note)")
    return status, why


@register_check("style_rotation", "auto",
                "Voice preset (when TTS) and caption style come from the policy lists and differ from the previous upload.")
def rotation_gate(clip, ctx):
    pol = ctx.get("policy") or {}
    voices = [v["name"] for v in pol.get("voice_presets", [])]
    styles = list((pol.get("caption_styles") or {}).keys())
    prev = ctx.get("previous_upload") or {}
    c, r = clip.get("commentary") or {}, clip.get("render") or {}
    out = []
    if c.get("tts_used"):
        vp = c.get("voice_preset")
        if vp not in voices:
            out.append(f"voice preset {vp!r} not in policy voice_presets")
        elif prev.get("voice_preset") == vp:
            out.append(f"voice preset {vp} repeats the previous upload")
    cs = r.get("caption_style")
    if r.get("captions", "OFF").startswith("BURNED"):
        if cs not in styles:
            out.append(f"caption style {cs!r} not in policy caption_styles")
        elif prev.get("caption_style") == cs:
            out.append(f"caption style {cs} repeats the previous upload")
    return (FAIL, "; ".join(out)) if out else (PASS, "rotation ok")


def _sha(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def build_ctx(pol, here):
    """Shared context for review.py / upload_private.py."""
    import script_checks
    spoiler = pol.get("spoiler_keywords_file")
    return {"min_commentary": max(0.60, float(pol.get("min_commentary_coverage", 0.60))),
            "spoiler_file": str(pathlib.Path(here) / spoiler) if spoiler else None, "policy": pol,
            "script_history": script_checks.read_history(), "previous_upload": script_checks.previous_upload()}


# ---------- reused-content basics ----------
@register_check("attribution", "auto", "Source streamer name and Twitch VOD URL present in description.")
def attribution_gate(clip, ctx):
    p, m = clip.get("provenance") or {}, clip.get("metadata") or {}
    desc = m.get("description", "")
    if not p.get("source_channel_name") or not p.get("source_url"):
        return FAIL, "provenance lacks streamer name or VOD URL"
    if p["source_channel_name"].lower() not in desc.lower() or p["source_url"] not in desc:
        return FAIL, "description must credit the streamer by name and link the VOD URL"
    return PASS, "streamer and VOD URL credited in description"


@register_check("transformation_note", "auto",
                "Reviewer wrote what this Short adds (commentary, context, edit) in at least 25 words.")
def transformation_gate(clip, ctx):
    words = len(str(clip.get("transformation_note", "")).split())
    return (PASS, f"{words} words") if words >= 25 else (FAIL, f"transformation note has {words} words; 25 required")


# ---------- gate 8: spoilers in metadata ----------
def spoiler_terms(ctx):
    terms = list(DEFAULT_SPOILERS)
    path = ctx.get("spoiler_file")
    if path and pathlib.Path(path).exists():
        terms += [l.strip().lower() for l in pathlib.Path(path).read_text().splitlines() if l.strip() and not l.startswith("#")]
    return terms


@register_check("metadata_spoiler_free", "auto", "Title, description and tags contain no spoiler keywords.")
def spoiler_gate(clip, ctx):
    m = clip.get("metadata") or {}
    if not m.get("title"):
        return FAIL, "no title set"
    text = " ".join([m.get("title", ""), m.get("description", ""), " ".join(m.get("tags", []))]).lower()
    hits = [t for t in spoiler_terms(ctx) if re.search(r"\b" + re.escape(t) + r"\b", text)]
    return (FAIL, "spoiler keywords: " + ", ".join(hits)) if hits else (PASS, "no spoiler keywords")


# ---------- gate 6 (part): disclosure ----------
def auto_disclosure(clip):
    """Fill containsSyntheticMedia when unanswered: true if TTS/AI voice or AI visuals are used, else false.
    Never flips an explicit answer (an explicit false with AI use still FAILS the gate)."""
    md = clip.setdefault("metadata", {})
    uses_ai = bool((clip.get("commentary") or {}).get("tts_used") or clip.get("ai_visuals_used"))
    if md.get("containsSyntheticMedia") is None:
        md["containsSyntheticMedia"] = uses_ai
        clip["synthetic_disclosure_reason"] = ("auto: TTS/AI voice or AI visuals used" if uses_ai
                                               else "auto: no TTS, AI voice or AI visuals recorded for this clip")
    return clip


@register_check("synthetic_disclosure", "auto",
                "containsSyntheticMedia is true whenever TTS or AI visuals are used.")
def disclosure_gate(clip, ctx):
    uses_ai = bool((clip.get("commentary") or {}).get("tts_used") or clip.get("ai_visuals_used"))
    flag = (clip.get("metadata") or {}).get("containsSyntheticMedia")
    if uses_ai and flag is not True:
        return FAIL, "AI voice/visuals used: containsSyntheticMedia must be true"
    if flag is None:
        return FAIL, "answer the synthetic-media question (true/false)"
    return PASS, f"containsSyntheticMedia={flag}"


@register_check("technical_qa", "auto", "qa.py technical checks passed on the final render.")
def technical_gate(clip, ctx):
    qa = clip.get("technical_qa") or {}
    return (PASS, "technical QA passed") if qa.get("status") == "PASS_TECHNICAL_ONLY" else (FAIL, "technical QA not passed: " + ",".join(qa.get("failures", ["not run"])))


# ---------- engine ----------
def init_clip(clip):
    clip.setdefault("compliance", {})
    for name in CHECKS:
        clip["compliance"].setdefault(name, {"status": PENDING})
    return clip


def evaluate(clip, ctx=None):
    """Re-run auto checks and hints. Human PASS stays only while its hint is not FAIL."""
    ctx = ctx or {}
    init_clip(clip)
    for name, spec in CHECKS.items():
        if name == "synthetic_disclosure":
            auto_disclosure(clip)
        entry = clip["compliance"][name]
        fn = spec["fn"]
        result = fn(clip, ctx) if fn else (WARN, "no automatic hint")
        if spec["kind"] == "auto":
            # WARN stays WARN (still blocking: only PASS unblocks)
            entry.update({"status": result[0] if result[0] in (PASS, FAIL, WARN) else FAIL, "evidence": result[1]})
        elif not applies(name, clip):
            entry.clear()
            entry.update({"status": PASS, "not_applicable": True, "evidence": "not applicable to this clip"})
        else:
            if entry.get("not_applicable"):
                entry.clear()
                entry["status"] = PENDING
            entry["hint"], entry["hint_evidence"] = result
            if result[0] == FAIL and entry.get("status") == PASS:
                entry.update({"status": PENDING, "revoked": "hint failed after sign-off: " + result[1]})
    return clip


def signoff(clip, name, by, note="", ctx=None):
    if name not in CHECKS or CHECKS[name]["kind"] != "human":
        raise ValueError(f"{name} is not a human check")
    if not applies(name, clip):
        raise ValueError(f"{name} does not apply to this clip")
    if not by.strip():
        raise ValueError("reviewer name required")
    evaluate(clip, ctx)
    entry = clip["compliance"][name]
    if entry.get("hint") == FAIL:
        raise PermissionError(f"cannot sign off {name}: {entry.get('hint_evidence')}")
    if entry.get("hint") == WARN and len(note.split()) < 5:
        raise PermissionError(f"{name} has a warning ({entry.get('hint_evidence')}); write a note of at least 5 words")
    entry.update({"status": PASS, "by": by.strip(), "note": note,
                  "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    return entry


def blockers(clip, ctx=None):
    evaluate(clip, ctx)
    return {n: e.get("evidence") or e.get("hint_evidence") or "pending human sign-off"
            for n, e in clip["compliance"].items() if e.get("status") != PASS}
