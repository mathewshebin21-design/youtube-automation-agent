"""Phase 2.7/2.8 compliance rules for the edit stage, shared by edit.py, render.py, review.py and upload_private.py.
The Node side (utils/cutscenecity/external-shorts.js) re-implements the same checks independently.

- Captions come ONLY from a separate creator mic stem (OBS multitrack stream or mic file). Mixed/game tracks are refused.
- Strong profanity in captions is masked (f******) from caption_policy.profanity_terms; any in the first 10 s is flagged.
  The caption mask does not touch the audio; the audio bleep is the separate per-clip choice below (phase 2.8).
- Caption text is scanned for story names and plot keywords (caption_policy + the shared spoiler lists); hits are flagged.
- captions_reviewed (human) approves the exact words.json (SHA-256 bound) for the exact final file.
- Edit style + effects are a per-clip human choice (signed edit_choice entry); renders refuse edits without one.
- Flash cut: off by default, at most 1 per clip, intensity <= 0.5.
- Phase 2.8 audio profanity: the mic stem transcript (word timestamps) is scanned for the same profanity_terms; the
  per-clip edit choice can bleep them (bleep=tone: 1 kHz tone, bleep=mute: silence) over the word timestamps.
  Strong profanity in the first 10 s blocks unless bleeped; profanity_audio_reviewed (human) is pinned to the final
  file SHA-256 and the profanity_audio record hash. Title and thumbnail text are checked against the same list.
- Phase 2.8.1: the FULL final mix (game dialogue, voiceover, mic) is transcribed and scanned too (mix_hits); bleep
  segments cover mic + mix hits. Because whisper misses words under music/game noise, the profanity_audio_reviewed
  sign-off must also record first_10s_full_mix_checked=true (a human listened to the first 10 s of the full mix).
"""
import hashlib
import json
import pathlib
import re

HERE = pathlib.Path(__file__).parent
EDIT_STYLES = ("off", "clean", "hype")
DEFAULT_CHOICE_STYLE = "clean"     # phase 2.7: default per-clip choice; hype is opt-in
EFFECTS = ("captions", "punch_in", "shake", "hook_zoom", "end_fade", "progress_bar", "flash_cut")
STYLE_EFFECTS = {"off": (), "clean": ("captions",), "hype": EFFECTS}
FLASH_MAX_PER_CLIP = 1
FLASH_MAX_INTENSITY = 0.5
FLASH_DEFAULT_INTENSITY = 0.5
WARN_FIRST_SECONDS = 10
PLACEHOLDER = "placeholder"
WORDS_PACKAGE_NAME = "captions.words.json"
BLEEP_MODES = ("off", "tone", "mute")
BLEEP_PAD_MS = 50                  # each bleep covers the word +/- 50 ms
BLEEP_TONE_HZ = 1000
AUDIO_SCANNED = "SCANNED"
MIC_REQUIRED = ("captions are generated only from a separate creator mic stem (OBS multitrack --mic-stream N or a "
                "--mic file); this clip has only the mixed Twitch/game track, so captions are refused")


class CaptionSourceError(ValueError):
    pass


def policy():
    return json.loads((HERE / "editorial-policy.json").read_text())


def caption_policy(pol=None):
    return (pol or policy()).get("caption_policy") or {}


# ---------- caption source ----------
def caption_source(opts):
    """{kind, media?, stream?, label} for a separate mic stem in the render options, else None (fail closed)."""
    if opts.get("audio_mode") not in ("mix", "mic_stem"):
        return None
    if opts.get("mic"):
        return {"kind": "mic_file", "media": str(opts["mic"]), "stream": "0:a:0", "label": "mic_file:" + pathlib.Path(opts["mic"]).name}
    if opts.get("mic_stream") is not None:
        return {"kind": "mic_stream", "media": None, "stream": f"0:a:{int(opts['mic_stream'])}", "label": f"mic_stream:{int(opts['mic_stream'])}"}
    return None


# ---------- profanity ----------
def _norm(token):
    return re.sub(r"[^a-z0-9']", "", str(token).lower())


def profanity_terms(pol=None):
    return [t.lower() for t in caption_policy(pol).get("profanity_terms", []) if t.strip()]


def is_profane(word, terms):
    n = _norm(word).replace("'", "")
    return bool(n) and any(n.startswith(t) for t in terms)


def mask_word(word):
    """Keep the first letter and any punctuation; letters/digits after the first become *."""
    out, seen = [], False
    for ch in word:
        if ch.isalnum():
            out.append(ch if not seen else "*")
            seen = True
        else:
            out.append(ch)
    return "".join(out)


def mask_words(words, pol=None):
    """Returns new word dicts: profane words masked and marked masked=True (the raw word is not kept)."""
    terms = profanity_terms(pol)
    out = []
    for w in words:
        d = dict(w)
        if is_profane(d["word"], terms):
            d["word"], d["masked"] = mask_word(d["word"]), True
        out.append(d)
    return out


# ---------- story names / plot keywords ----------
def keyword_terms(pol=None):
    """(active terms, list_incomplete). PLACEHOLDER* entries are ignored but mark the list as not filled in."""
    cp = caption_policy(pol)
    raw = list(cp.get("story_names", [])) + list(cp.get("plot_keywords", []))
    incomplete = any(str(t).strip().lower().startswith(PLACEHOLDER) for t in raw)
    terms = [str(t).strip() for t in raw if str(t).strip() and not str(t).strip().lower().startswith(PLACEHOLDER)]
    shared = json.loads((HERE / "spoiler-defaults.json").read_text())["terms"]
    extra = HERE / "spoiler-keywords.txt"
    if extra.exists():
        shared += [l.strip() for l in extra.read_text().splitlines() if l.strip() and not l.startswith("#")]
    seen, out = set(), []
    for t in terms + shared:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out, incomplete


def keyword_hits(words, pol=None):
    terms, _ = keyword_terms(pol)
    toks = [_norm(w["word"]) for w in words]
    hits = []
    for term in terms:
        parts = [_norm(x) for x in term.split() if _norm(x)]
        if not parts:
            continue
        for i in range(len(toks) - len(parts) + 1):
            if toks[i:i + len(parts)] == parts:
                hits.append({"term": term, "t": words[i]["start"]})
    return sorted(hits, key=lambda h: h["t"])


def caption_flags(words, pol=None):
    """Review flags for captions_reviewed. Any non-empty flag needs a 5+ word reviewer note."""
    terms = profanity_terms(pol)
    first = caption_policy(pol).get("profanity_warn_first_seconds", WARN_FIRST_SECONDS)
    masked = [w for w in words if w.get("masked")]
    _, incomplete = keyword_terms(pol)
    return {"profanity_masked": len(masked),
            "profanity_first_10s": [w["start"] for w in masked if float(w["start"]) < first],
            "unmasked_profanity": [w["start"] for w in words if not w.get("masked") and is_profane(w["word"], terms)],
            "keyword_hits": keyword_hits(words, pol),
            "keyword_list_incomplete": incomplete,
            "audio_bleeped": False}


def flag_reasons(flags):
    out = []
    if flags.get("profanity_first_10s"):
        out.append(f"profanity in the first 10 s at {flags['profanity_first_10s']}")
    if flags.get("keyword_hits"):
        out.append("story name / plot keyword in captions: " + ", ".join(sorted({h["term"] for h in flags["keyword_hits"]})))
    if flags.get("keyword_list_incomplete"):
        out.append("caption keyword list still has PLACEHOLDER entries (Shebin/Compliance must fill it in)")
    if flags.get("profanity_masked"):
        out.append(f"{flags['profanity_masked']} masked word(s): the caption mask alone leaves audio NOT bleeped (see profanity_audio / --bleep)")
    return out


def sha256_record(obj):
    """Same canonical hash as gatelog.sha256_json / Node sha256Json (sorted keys, compact, ints only)."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha256_bytes(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


# ---------- phase 2.8: audio profanity (mic stem transcript) + clean title/thumbnail ----------
def _ms(sec):
    return int(round(float(sec) * 1000))


def bleep_segments(hits):
    """[[start_ms, end_ms]] covering each hit +/- BLEEP_PAD_MS (merged when they overlap). Ints only (signed/hashed)."""
    segs = []
    for h in sorted(hits, key=lambda h: h["start_ms"]):
        a, b = max(0, h["start_ms"] - BLEEP_PAD_MS), h["end_ms"] + BLEEP_PAD_MS
        if segs and a <= segs[-1][1]:
            segs[-1][1] = max(segs[-1][1], b)
        else:
            segs.append([a, b])
    return segs


def _profane_hits(words, terms):
    out = []
    for w in (words or []):
        if w.get("masked") or is_profane(w["word"], terms):
            out.append({"word": w["word"] if w.get("masked") else mask_word(w["word"]),
                        "start_ms": _ms(w["start"]), "end_ms": _ms(w.get("end", w["start"]))})
    return out


MIX_NOT_SCANNED = "NOT_SCANNED"


def all_hits(rec):
    return list((rec or {}).get("hits") or []) + list((rec or {}).get("mix_hits") or [])


def audio_profanity_record(words, bleep="off", source="", status=AUDIO_SCANNED, pol=None, mix_words=None, mix_status=None):
    """Int-only record of strong profanity in the mic stem transcript (`hits`) and, since phase 2.8.1, in the
    FULL final mix transcript (`mix_hits`: game dialogue, voiceover, mic). Words may be raw or already masked
    (masked=True); the raw word is never stored. Bleep segments cover both lists when bleep != off."""
    terms = profanity_terms(pol)
    hits = _profane_hits(words, terms)
    if mix_status is None:
        mix_status = AUDIO_SCANNED if mix_words is not None else MIX_NOT_SCANNED
    mix_hits = _profane_hits(mix_words, terms) if mix_status == AUDIO_SCANNED else []
    if bleep not in BLEEP_MODES:
        raise ValueError("bleep must be off, tone or mute")
    rec = {"status": status, "source": source, "terms": len(terms), "hits": hits,
           "mix_status": mix_status, "mix_hits": mix_hits, "bleep": bleep,
           "bleeped_segments": bleep_segments(hits + mix_hits) if (bleep != "off" and status == AUDIO_SCANNED) else []}
    return {**rec, **audio_profanity_state(rec, pol)}


def audio_profanity_state(rec, pol=None):
    """Recomputed from hits + bleeped_segments (never trusts stored flags): which hits stay audible."""
    first_ms = int(caption_policy(pol).get("profanity_warn_first_seconds", WARN_FIRST_SECONDS)) * 1000
    segs = (rec or {}).get("bleeped_segments") or []
    covered = lambda h: any(a <= h["start_ms"] and h["end_ms"] <= b for a, b in segs)  # noqa: E731
    hits = all_hits(rec)
    unbleeped = sorted({h["start_ms"] for h in hits if not covered(h)})
    return {"hit_count": len(hits), "mix_hit_count": len((rec or {}).get("mix_hits") or []),
            "first_10s_ms": sorted({h["start_ms"] for h in hits if h["start_ms"] < first_ms}),
            "unbleeped_ms": unbleeped, "unbleeped_first_10s_ms": [t for t in unbleeped if t < first_ms]}


def audio_profanity_problems(rec, choice=None, pol=None):
    """Blocking problems for the audio profanity record (manifest consistency; Node re-checks the same)."""
    if not rec:
        return ["profanity_audio: the mic stem was not scanned for profanity (record an edit choice: review.py edit "
                "--by NAME [--bleep tone|mute], any style incl. off, on a mic-stem render)"]
    out = []
    if rec.get("status") != AUDIO_SCANNED:
        out.append(f"profanity_audio: scan {rec.get('status')} (faster-whisper needed on the mic stem); failing closed")
    if rec.get("mix_status") != AUDIO_SCANNED:
        out.append(f"profanity_audio: full-mix scan {rec.get('mix_status') or MIX_NOT_SCANNED} (game dialogue/voiceover "
                   "not covered; re-run review.py edit); failing closed")
    st = audio_profanity_state(rec, pol)
    if st["unbleeped_first_10s_ms"]:
        out.append(f"strong profanity in the first 10 s is not bleeped (at {st['unbleeped_first_10s_ms']} ms): "
                   "review.py edit --bleep tone|mute")
    if choice and (choice.get("bleep") or "off") != (rec.get("bleep") or "off"):
        out.append("profanity_audio: bleep differs from the recorded human edit choice")
    if (rec.get("bleep") or "off") != "off" and rec.get("status") == AUDIO_SCANNED and all_hits(rec) and \
            rec.get("bleeped_segments") != bleep_segments(all_hits(rec)):
        out.append("profanity_audio: bleeped segments do not cover the profanity hits")
    return out


def text_profanity(fields, pol=None):
    """{field: [masked hits]} for strong profanity in short text fields (title, thumbnail text)."""
    terms = profanity_terms(pol)
    out = {}
    for name, text in fields.items():
        toks = re.split(r"[\s/_\-]+", str(text or ""))
        hits = [mask_word(t) for t in toks if is_profane(t, terms)]
        if hits:
            out[name] = hits
    return out


# ---------- per-clip human edit choice ----------
def parse_effects(text):
    if text is None:
        raise ValueError("--effects is required (comma list, or 'none'): the edit is a per-clip human choice")
    items = [e.strip().lower() for e in str(text).split(",") if e.strip()]
    return [] if items in ([], ["none"]) else items


def validate_choice(choice):
    """Normalise and validate {edit_style, effects, by, flash_intensity_pct?, caption_style?}. Raises ValueError."""
    if not isinstance(choice, dict):
        raise ValueError("edit choice must be a dict recorded by a human (review.py edit)")
    style = str(choice.get("edit_style", "")).strip().lower()
    style = "off" if style == "none" else style
    if style not in EDIT_STYLES:
        raise ValueError("edit_style must be off, clean or hype")
    if not str(choice.get("by", "")).strip():
        raise ValueError("edit choice needs the reviewer name (by)")
    effects = choice.get("effects")
    if not isinstance(effects, list) or any(not isinstance(e, str) for e in effects):
        raise ValueError("effects must be an explicit list chosen by a human")
    bad = [e for e in effects if e not in STYLE_EFFECTS[style]]
    if bad:
        raise ValueError(f"effects {bad} are not allowed for edit style {style} (allowed: {list(STYLE_EFFECTS[style])})")
    if style != "off" and not effects:
        raise ValueError(f"edit style {style} needs at least one effect (or choose off)")
    pct = choice.get("flash_intensity_pct")
    if "flash_cut" in effects:
        pct = int(round(FLASH_DEFAULT_INTENSITY * 100)) if pct in (None, "") else pct
        if not isinstance(pct, int) or isinstance(pct, bool) or not 0 < pct <= int(FLASH_MAX_INTENSITY * 100):
            raise ValueError(f"flash intensity must be > 0 and <= {FLASH_MAX_INTENSITY}")
    else:
        pct = 0
    bleep = str(choice.get("bleep") or "off").strip().lower()
    if bleep not in BLEEP_MODES:
        raise ValueError("bleep must be off, tone (1 kHz) or mute")
    return {"edit_style": style, "effects": sorted(set(effects), key=EFFECTS.index), "by": str(choice["by"]).strip(),
            "flash_intensity_pct": pct, "caption_style": choice.get("caption_style") or "", "bleep": bleep}


def flash_plan(joins, enabled, intensity=FLASH_DEFAULT_INTENSITY):
    """Hard limits: off unless enabled, at most FLASH_MAX_PER_CLIP joins, intensity <= FLASH_MAX_INTENSITY."""
    if not enabled:
        return []
    if not 0 < float(intensity) <= FLASH_MAX_INTENSITY:
        raise ValueError(f"flash intensity must be > 0 and <= {FLASH_MAX_INTENSITY}")
    return [float(j) for j in list(joins)[:FLASH_MAX_PER_CLIP]]


# ---------- gate helpers (manifest only; no log) ----------
def captions_burned(render):
    return str((render or {}).get("captions") or "OFF").startswith("BURNED")


def render_edit_problems(clip):
    """Consistency of the render with the recorded human edit choice, flash limits and caption source."""
    r, ec = clip.get("render") or {}, clip.get("edit_choice") or {}
    style = r.get("edit_style") or "off"
    out = []
    if style != "off" or r.get("edit_effects"):
        if not ec.get("by"):
            out.append(f"edit style {style} was applied without a recorded human edit choice (review.py edit)")
        elif ec.get("edit_style") != style or list(ec.get("effects") or []) != list(r.get("edit_effects") or []):
            out.append("render edit style/effects differ from the recorded human edit choice")
    flashes = r.get("flash_cuts") or []
    if len(flashes) > FLASH_MAX_PER_CLIP:
        out.append(f"{len(flashes)} flash cuts (max {FLASH_MAX_PER_CLIP} per clip)")
    if flashes and not 0 < float(r.get("flash_intensity") or 0) <= FLASH_MAX_INTENSITY:
        out.append(f"flash intensity {r.get('flash_intensity')} above {FLASH_MAX_INTENSITY}")
    if captions_burned(r):
        if not str(r.get("caption_source") or "").startswith("mic_"):
            out.append("captions were not generated from a separate mic stem (mixed/game track captions are refused)")
        if not r.get("words_json_sha256"):
            out.append("burned captions have no words.json hash to review")
    return out


# ---------- signed-log checks (review.py approve/export and upload_private) ----------
def latest(entries, action, clip_file, **match):
    rows = [e for e in entries if e.get("action") == action and e.get("clip") == clip_file
            and all(e.get(k) == v for k, v in match.items())]
    return rows[-1] if rows else None


def signed_problems(clip, entries, file_sha, words_path):
    out = list(render_edit_problems(clip))
    r = clip.get("render") or {}
    pa = r.get("profanity_audio")
    if (r.get("edit_style") or "off") != "off" or ((pa or {}).get("bleep") or "off") != "off":
        e = latest(entries, "edit_choice", clip["file"])
        ec = clip.get("edit_choice") or {}
        if not e:
            out.append("edit_choice: no signed per-clip human edit choice")
        elif (e.get("edit_style"), e.get("effects"), e.get("flash_intensity_pct"), e.get("by"), e.get("bleep") or "off") != \
                (ec.get("edit_style"), ec.get("effects"), ec.get("flash_intensity_pct"), ec.get("by"), ec.get("bleep") or "off"):
            out.append("edit_choice: manifest choice differs from the signed choice")
    # phase 2.8: audio profanity scan + profanity_audio_reviewed pinned to the final file and the record hash
    out += audio_profanity_problems(pa, clip.get("edit_choice"))
    if pa:
        so = latest(entries, "signoff", clip["file"], check="profanity_audio_reviewed", file_sha256=file_sha)
        if not so or so.get("final_sha256") != file_sha or so.get("profanity_audio_sha256") != sha256_record(pa):
            out.append("profanity_audio_reviewed: no signed review pinned to this exact final file + audio scan")
        elif so.get("first_10s_full_mix_checked") is not True:
            out.append("profanity_audio_reviewed: the sign-off must confirm the first 10 s of the FULL mix were listened "
                       "to (--first-10s-full-mix-checked)")
        elif all_hits(pa) and len(str(so.get("note") or "").split()) < 5:
            out.append("profanity_audio_reviewed: profanity found, the sign-off needs a 5+ word note")
    if captions_burned(r):
        p = pathlib.Path(words_path) if words_path else None
        if not p or not p.exists():
            out.append("captions_reviewed: words.json missing")
            return out
        sha = sha256_bytes(p)
        if sha != r.get("words_json_sha256"):
            out.append("captions_reviewed: words.json changed after render")
        so = latest(entries, "signoff", clip["file"], check="captions_reviewed", file_sha256=file_sha)
        if not so or so.get("words_json_sha256") != sha:
            out.append("captions_reviewed: no signed caption review for this exact words.json + file")
        flags = caption_flags(json.loads(p.read_text()))
        if flags["unmasked_profanity"]:
            out.append("captions contain unmasked strong profanity")
        if so and flag_reasons(flags) and len(str(so.get("note") or "").split()) < 5:
            out.append("captions_reviewed: flagged captions need a 5+ word reviewer note")
    return out
