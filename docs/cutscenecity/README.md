# CutsceneCity Twitch → YouTube Shorts: HANDOVER

The handover for whoever continues this work, such as another AI assistant. Everything here comes from the repo on branch `cutscenecity-phase2.7-compliance`. Anything not checked against the code or an official source is marked UNVERIFIED.

## Owner rules (non-negotiable)
- The source is only Shebin's own Twitch channel `cutscenecity` (creator-owned gate, fail closed). The destination is YouTube @cutscenecity.
- Uploads are **private only**. Each upload needs its own human approval, and nothing ever auto-publishes or schedules. CI is review-only and never uploads.
- **No push, merge or upload without Shebin's explicit OK for that specific action.** Never merge `gta6-improvements`.
- Credentials stay on Shebin's machine (`~/.cutscenecity/`). Never commit `.env`, OAuth client JSON, tokens, cookies, VODs or media.
- Never invent stats or GTA 6 plot facts; mark unknowns UNVERIFIED. Titles, descriptions, scripts and transformation notes are Shebin's own text: the code never writes them.

## Architecture
```
Twitch VOD (own) / OBS multitrack recording
  → tools/twitch-shorts/pipeline.py   owner check via yt-dlp -J (before download), signals.py ranking, PRE-EDIT 9:16 render (render.py), qa.py, manifest.json
  → tools/twitch-shorts/review.py     status | set | precheck | commentary | edit | script | paid | signoff | approve | export
       compliance.py  default-deny gates (auto + human)      edit_gates.py  phase-2.7 edit/caption rules
       gatelog.py     HMAC-signed review log + upload ledger   overlay_scan.py  chat/alert flagging (pre-edit render)
       edit.py        captions (ASS word-by-word) + effects    script_checks.py rotation/similarity
  → package dir (video.mp4, package.json, clip.json, review_log.jsonl, agent-import.json, captions.words.json)
  → either tools/twitch-shorts/upload_private.py (local, private, re-verifies everything)
    or Node: utils/cutscenecity/external-shorts.js  POST /api/gta6/external-shorts (ingest, never uploads)
             + per-upload approval route (the only path that calls videos.insert, privacyStatus=private)
```
- Policy: `tools/twitch-shorts/editorial-policy.json` (caps, caption_policy, edit_policy, voice/caption styles, layout profiles). Spoiler lists: `spoiler-defaults.json` and `spoiler-keywords.txt`.
- Python and Node verify independently. Node never trusts the gate statuses saved by Python.

## Phases (local commits on top of fork master e973d51)
| Commit | Phase | Summary |
|---|---|---|
| ccad4e8 | 1 | Multi-signal selection notes, 9:16 layouts + captions + loudnorm, default-deny gates, signed review log, gated private upload package |
| 2099db3 | 2 | Own VODs only, TTS counts only with forced synthetic disclosure, daily cap 1, blur default, Node ingest route with signed-package verification |
| 6050263 | 2.1 | Creator-owned gate 1, commentary gate 4 v3 (60% coverage, live reaction kept) |
| 8915135 | 2.2 | Hard daily cap 1, overlays/third-party check, explicit paid promotion, owner default `cutscenecity`, game audio kept by default |
| a9cc76e | 2.3 | Mixed-track signed path, auto QA/credit/disclosure, status guidance, OBS docs |
| 2b84976 | 2.4 | Upscale ON by default (2160x3840) |
| 2d33081 | 2.5 | Daily cap raised to 2 (Shebin approved at the time) |
| 02c223c | 2.6 | Automatic edit stage, `hype` default (kept on its own branch, e.g. `cutscenecity-phase2.6-hype`) |
| (2.7 fixes) | 2.7 | Compliance fixes 1-8: per-clip signed edit choice, mic-stem-only captions, `captions_reviewed` bound to words.json, profanity masking + first-10s flag, caption keyword scan, pre-edit overlay scan, flash ≤ 1 at ≤ 0.5 |
| (2.7 defaults) | 2.7 | Game audio stripped by default (`--keep-game-audio` opt-in), separate mic required (mixed-track opt-in `CUTSCENECITY_ALLOW_MIXED_TRACK`), hard daily cap 1, default edit choice `clean` (hype opt-in) |
| (2.7 docs) | 2.7 | This `docs/cutscenecity/` handover |
| (2.8) | 2.8 | Mixed-track bypass removed, first render `mic_stem` (superseded by the next row), audio-profanity gate (`profanity_audio_reviewed`, optional bleep, first-10 s block, clean title/thumbnail), music wording fix, VOD ids scrubbed |
| (2.8.1) | 2.8.1 | Live-voice floor 30% on the mic stem only, independent music-note re-check (verify_package + Node), full-mix profanity scan + signed first-10s full-mix confirmation, stale mixed-track docs fixed |
| (2.8 game audio) | 2.8 | Shebin's override: game audio KEPT by default (`mix`: game + mic at 1.0 + optional voiceover), `--strip-game-audio` opt-in, `--keep-game-audio` no-op, first render keeps game audio, music_risk wording |
| (2.8 workflow) | 2.8 | Separate, droppable commit: the review workflow no longer uploads `output/short_*.mp4` / manifest artifacts |

Remote state, as last known: `origin/cutscenecity-phase1-tweaks` at 9ffcb12 (phases up to 2.5); `cutscenecity-phase2.6-hype` and `cutscenecity-phase2.7-compliance` were pushed with Shebin's approval. Phase 2.8 is local only. Which commit hashes belong to what is in `/workspace/gta6-automation/patches/push-manifest-2.7.txt` (box only).

## How to run
```bash
# tests (Python needs ffmpeg + opencv + faster-whisper installed; the suite mocks whisper and YouTube)
node --test tests/cutscenecity-external-shorts.test.js
python -m unittest discover -s tools/twitch-shorts -p "test_*.py"
# (npm run test:cutscenecity runs both)

# one clip, end to end (local, private)
export CUTSCENECITY_OWNER_TWITCH_LOGIN=cutscenecity CUTSCENECITY_REVIEW_KEY=<32+ random chars, never commit>
python tools/twitch-shorts/pipeline.py --input rec.mkv --info-json vod.info.json --render --window 585-615 --mic-stream 1 --output out  # first render = game audio + mic stem
python tools/twitch-shorts/review.py commentary --output out --clip short_01.mp4 --mic-stream 1      # game audio kept (add --audio VO.wav for a voiceover, --strip-game-audio to drop it)
python tools/twitch-shorts/review.py edit       --output out --clip short_01.mp4 --by Shebin          # default clean + captions; scans mic audio for profanity
                                                                        # add --bleep tone|mute to bleep flagged words (required if any are in the first 10 s)
python tools/twitch-shorts/review.py precheck   --output out --clip short_01.mp4                      # overlay scan on the pre-edit render
python tools/twitch-shorts/review.py status     --output out --clip short_01.mp4                      # what is still blocking + fix commands
python tools/twitch-shorts/review.py signoff    --output out --clip short_01.mp4 --check <gate> --by Shebin --note "..."
python tools/twitch-shorts/review.py paid       --output out --clip short_01.mp4 --value none --by Shebin
python tools/twitch-shorts/review.py approve    --output out --clip short_01.mp4 --by Shebin
python tools/twitch-shorts/review.py export     --output out --clip short_01.mp4 --packages packages
```
For hype, which is opt-in: `review.py edit --style hype --effects captions,punch_in,end_fade --by Shebin`. Allowed effects are `captions, punch_in, shake, hook_zoom, end_fade, progress_bar, flash_cut`. A flash cut is capped at 1 per clip at intensity ≤ 0.5.

## Gates
See `GATES.md` (generated from `compliance.CHECKS`), and `OBS-MULTITRACK.md` for the mic-track setup the gates now require.

## Other docs in this folder
- `CLIPPERS-EVAL.md`: evaluation of open-source clippers and hosting options (copied from the research workspace; its dated facts are as of its writing).
- `CUTSCENECITY-PHASE1.md`: the long phase 1 to 2.3 guide (audit findings, setup, OAuth Desktop flow). **Its cap and default-audio statements are out of date**; the code and the 2.7 sections of `tools/twitch-shorts/README.md` are authoritative.
- `youtube-api-audit/`: a DRAFT YouTube API audit/quota package. Not submitted; Shebin decides.

## Open items (as of phase 2.8.1)
- Shebin still has to confirm the 2.7 defaults with the coordinator (GTA6 YouTube Automator), and Compliance still has to review the 2.7 patch. 2.6 `hype` stays recoverable at 02c223c.
- `caption_policy.story_names` / `plot_keywords` hold PLACEHOLDER entries that Shebin or Compliance must fill in. Until then every caption review is flagged.
- Phase 2.8: audio profanity is scanned and can be bleeped per clip (`--bleep tone|mute`); obfuscated spellings and misheard words are not caught.
- Compliance's conditional pass covers ONE private test only. Conditions: gameplay only, no Twitch-muted ranges, all sign-offs done, a 25+ word transformation note, the clean edit, and waiting for Studio Checks before any publish decision.
- The 12 "final" shorts rendered under 2.6 (outside the repo) keep game audio and some contain cutscenes and dialogue, so they do NOT meet these conditions.
