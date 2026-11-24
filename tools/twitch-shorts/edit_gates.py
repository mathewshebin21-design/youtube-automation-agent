"""Phase 2.7 compliance rules for the edit stage, shared by edit.py, render.py, review.py and upload_private.py.
The Node side (utils/cutscenecity/external-shorts.js) re-implements the same checks independently.

- Captions come ONLY from a separate creator mic stem (OBS multitrack stream or mic file). Mixed/game tracks are refused.
- Strong profanity in captions is masked (f******) from caption_policy.profanity_terms; any in the first 10 s is flagged.
  LIMITATION: the audio itself is NOT bleeped.
- Caption text is scanned for story names and plot keywords (caption_policy + the shared spoiler lists); hits are flagged.
- captions_reviewed (human) approves the exact words.json (SHA-256 bound) for the exact final file.
- Edit style + effects are a per-clip human choice (signed edit_choice entry); renders refuse edits without one.
- Flash cut: off by default, at most 1 per clip, intensity <= 0.5.
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
        out.append(f"{flags['profanity_masked']} masked word(s): audio is NOT bleeped")
    return out


def sha256_bytes(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


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
    return {"edit_style": style, "effects": sorted(set(effects), key=EFFECTS.index), "by": str(choice["by"]).strip(),
            "flash_intensity_pct": pct, "caption_style": choice.get("caption_style") or ""}


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
    if (r.get("edit_style") or "off") != "off":
        e = latest(entries, "edit_choice", clip["file"])
        ec = clip.get("edit_choice") or {}
        if not e:
            out.append("edit_choice: no signed per-clip human edit choice")
        elif (e.get("edit_style"), e.get("effects"), e.get("flash_intensity_pct"), e.get("by")) != \
                (ec.get("edit_style"), ec.get("effects"), ec.get("flash_intensity_pct"), ec.get("by")):
            out.append("edit_choice: manifest choice differs from the signed choice")
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
