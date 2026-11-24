# CutsceneCity gate list (generated from code, branch `cutscenecity-phase2.8`)

Generated from `tools/twitch-shorts/compliance.py` (`compliance.CHECKS`, 19 registered checks). Every check starts as PENDING, and only PASS unblocks it (default-deny).
- `auto` checks are computed from the manifest and media.
- `human` checks need `review.py signoff --check NAME --by NAME [--note ...]`, which is signed into the HMAC review log and bound to the final file's SHA-256. A WARN hint needs a note of 5+ words; a FAIL hint blocks the sign-off.

| Gate | Kind | What it requires |
|---|---|---|
| `creator_owned_source` | auto | Source VOD belongs to the configured owner channel (yt-dlp metadata vs CUTSCENECITY_OWNER_TWITCH_LOGIN / CUTSCENECITY_OWNER_TWITCH_ID). No third-party sources. |
| `vod_rights_confirmed` | human | A person confirms the VOD is from their own channel and the provenance record is true. |
| `no_story_cutscene` | human | A person confirms the clip is player gameplay, not a story cutscene (Rockstar story content). |
| `music_risk_cleared` | human | Game audio is KEPT by default (audio_mode mix: original game audio, which can include licensed in-game radio or score, plus the creator mic and any voiceover). A person listens to the WHOLE final file for licensed music/radio (Content ID risk) and signs off with a 5+ word note; fingerprint pre-check result attached. If licensed music is audible: re-render with --strip-game-audio (mic_stem) or pick another window. |
| `overlays_third_parties_cleared` | human | A person confirms chat, alert and username regions are blurred in the FINAL render, no viewer TTS/donation messages are audible, and no guest or voice-chat audio is in the mix. |
| `captions_reviewed` | human | A person read the burned captions (the exact words.json, SHA-256 bound) against the final file: words are right, strong profanity is masked, no story names or plot dialogue. (Audio profanity is the separate profanity_audio_reviewed check.) |
| `profanity_audio_reviewed` | human | A person listened to the final file for strong profanity. The mic stem transcript is scanned against caption_policy.profanity_terms; flagged words can be bleeped (review.py edit --bleep tone/mute: 1 kHz tone or mute over the word timestamps). Strong profanity in the first 10 s blocks unless bleeped. The signed sign-off is pinned to the final file SHA-256 and the profanity_audio record hash; a note of 5+ words is required when anything was found. Phase 2.8.1: the FULL final mix (game dialogue, voiceover) is transcribed and scanned too, and the sign-off must confirm the first 10 s of the full mix were listened to (--first-10s-full-mix-checked). |
| `title_thumbnail_profanity_free` | auto | Title and thumbnail text (package metadata: metadata.title, metadata.thumbnail_text) contain no strong profanity from caption_policy.profanity_terms. |
| `paid_promotion_declared` | auto | Reviewer declared paid_promotion as none or present (signed); sent explicitly on upload. |
| `original_commentary` | auto | Creator mic + voiceover/TTS (energy VAD on the combined commentary bus) covers at least 60% of runtime, AND the creator's live voice alone (mic stem only) covers at least 30% (phase 2.8.1 floor: TTS can top up to 60% but never replaces the creator). TTS counts only when CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY is on (default) and containsSyntheticMedia is true. |
| `live_reaction_preserved` | auto | The creator's real mic/reaction track is in the final mix at full level (never muted or ducked). |
| `commentary_script` | auto | When TTS is used: a human-edited script is stored and approved in the signed review log (review.py script). |
| `script_originality` | auto | Script vs the last 30 approved/uploaded scripts: flag at 40% shingle overlap (needs a reviewer note), reject above 50%; any reused opener or CTA line is rejected. |
| `style_rotation` | auto | Voice preset (when TTS) and caption style come from the policy lists and differ from the previous upload; edit style + effects match the per-clip human edit choice; flash cut <= 1 per clip at <= 0.5 intensity. |
| `attribution` | auto | Source streamer name and Twitch VOD URL present in description. |
| `transformation_note` | auto | Reviewer wrote what this Short adds (commentary, context, edit) in at least 25 words. |
| `metadata_spoiler_free` | auto | Title, description and tags contain no spoiler keywords. |
| `synthetic_disclosure` | auto | containsSyntheticMedia is true whenever TTS or AI visuals are used. |
| `technical_qa` | auto | qa.py technical checks passed on the final render. |

## Game audio and music (phase 2.8: KEPT by default, Shebin's override)
- Game audio is KEPT by default: the first render (`pipeline.py --mic-stream N` / `--mic FILE`) and `review.py commentary` render `audio_mode=mix` = the original game audio (music volume default 1.0, unchanged) + the separate creator mic stem at gain 1.0 + an optional voiceover/TTS on top, with no ducking. `--keep-game-audio` is accepted as a no-op.
- Stripping game audio is the opt-in `review.py commentary --strip-game-audio` (`audio_mode=mic_stem`).
- Kept game audio can contain licensed in-game radio or score, so `music_risk_cleared` always WARNs on a kept-audio render: a person must listen to the WHOLE final file and sign off with a 5+ word note. The local fingerprint pre-check is only a hint and is not Content ID. If licensed music is audible, re-render with `--strip-game-audio` or pick another window; after upload, wait for YouTube's copyright checks before any publish decision.
- Without a mic stem the first render keeps the source audio (`audio_mode=source`). It fails `original_commentary` and `live_reaction_preserved` until `review.py commentary --mic-stream N|--mic FILE` adds the mic stem. `review.py commentary --audio VOICE` without a mic renders game + voiceover for review, but the same two gates FAIL (no mixed-track bypass).

## Mixed-track path: removed (phase 2.8)
The phase 2.6 mixed-track path (one Twitch VOD track + a signed `mixed_track_commentary_confirmed`) is removed entirely. `CUTSCENECITY_ALLOW_MIXED_TRACK` and policy `mixed_track_path_enabled` are no longer read: a clip without a separate creator mic stem always FAILs `original_commentary` and `live_reaction_preserved` (the 60% measurement runs on the mic stem only), in Python, `upload_private.verify_package` and the Node gate.

## Audio profanity (phase 2.8)
- Whenever a human edit choice is recorded on a mic-stem render (`review.py edit --by NAME`, any style including `off`), the mic stem transcript (faster-whisper word timestamps; the captions transcript is reused) is scanned for `caption_policy.profanity_terms`. The result is `render.profanity_audio` (int ms, masked words only). No faster-whisper means status `UNAVAILABLE_NO_FASTER_WHISPER`, which fails closed.
- Optional bleep, part of the signed per-clip edit choice: `review.py edit --bleep tone` (1 kHz sine at -12 dBFS over each word +/-50 ms) or `--bleep mute`; default `off`. It is applied to the final audio (video stream copied). In `mix` renders the bleep also mutes the game audio over the segment.
- Strong profanity starting in the first `profanity_warn_first_seconds` (10 s) blocks the clip unless bleeped.
- `profanity_audio_reviewed` (human) must be signed for the exact final file: the log entry carries `final_sha256` and `profanity_audio_sha256` (hash of the record); any re-render or re-scan invalidates it. With hits, the note needs 5+ words.
- `title_thumbnail_profanity_free` (auto) checks `metadata.title` and `metadata.thumbnail_text` against the same list (prefix match per token; obfuscated spellings like `f*ck` are not caught).

## Phase 2.8.1 (Compliance conditional pass)
- **Live-voice floor:** `original_commentary` FAILs unless the creator's live voice, measured on the mic stem ONLY, covers at least 30% of the runtime (`min_live_voice_coverage`, policy may only raise it). TTS/voiceover may top the total up to 60% but cannot replace the creator (20% mic + 50% TTS = FAIL; 35% mic + 30% TTS = PASS). No mic stem = hard FAIL. Re-checked independently by `upload_private.verify_package` and the Node gate.
- **Music note:** when `audio_mode` is `mix` or `source` (game/source audio in the final mix), `verify_package` and Node ingest each require the latest signed `music_risk_cleared` sign-off for the exact file to have a 5+ word note.
- **Full-mix profanity:** the full final mix (game dialogue, voiceover, mic) is transcribed and scanned as well as the mic stem (`profanity_audio.mix_hits`, `mix_status`; not scanned or unavailable = fail closed). Bleep segments cover both. Because whisper misses words under music and game noise, the signed `profanity_audio_reviewed` entry must also carry `first_10s_full_mix_checked: true` (`review.py signoff ... --first-10s-full-mix-checked`).

## Extra signed-log requirements (review.py approve/export, upload_private.verify_package, Node ingest)
- `paid_promotion`: a signed `review.py paid --value none|present` for this exact file.
- `overlay_scan`: run on this exact final file (phase 2.7 scans the pre-edit render, see fix 6).
- `commentary_script`: a signed script approval when TTS or a script is used.
- `edit_choice` (phase 2.7, bleep added in 2.8): a signed per-clip human choice of style, effects and bleep whenever an edit or a bleep was applied.
- `captions_reviewed` (phase 2.7): the signed sign-off carries `words_json_sha256` of the exact words.json; the package ships `captions.words.json`.
- `profanity_audio_reviewed` (phase 2.8): signed with `final_sha256` + `profanity_audio_sha256`; phase 2.8.1 adds `first_10s_full_mix_checked: true`.
- `music_risk_cleared` (phase 2.8.1): 5+ word note re-checked by verify_package and Node when game/source audio is kept.
- `approve`: a signed approval of the exact file, metadata, provenance, script hash and paid value.
- Daily cap: hard maximum 1 per IST day (env `CUTSCENECITY_DAILY_CAP` can only lower it). There is a duplicate/overlap check against the upload ledger. Uploads are private only.

## Node (`utils/cutscenecity/external-shorts.js`)
`checkClipGates` and the ingest verification re-check the gates independently and never trust the statuses Python saved:
- creator-owned source, attribution, spoilers, synthetic disclosure, resolution;
- separate mic stem always required (mixed track refused, no opt-in), mic at gain 1.0, 30% live-voice floor (mic stem only) + 60% commentary, script reuse, rotation (game audio kept by default: no opt-in check);
- the edit choice (incl. bleep), flash limits, mic-only captions and the words.json review;
- audio profanity record (recomputed state, first-10 s block, bleep vs choice) and clean title/thumbnail text;
- all compliance statuses PASS.
`REQUIRED_HUMAN_CHECKS` = `vod_rights_confirmed`, `no_story_cutscene`, `music_risk_cleared`, `overlays_third_parties_cleared`, `profanity_audio_reviewed`, plus policy `extra_human_checks` and `captions_reviewed` (burned captions).

## Policy `required_gates` list (editorial-policy.json)
`attribution`, `audio_quality`, `caption_accuracy`, `creator_owned_source`, `daily_cap`, `deduplication`, `duplicate_check`, `human_approval`, `media_decode`, `metadata_spoiler_free`, `music_risk_cleared`, `no_story_cutscene`, `original_commentary`, `overlays_third_parties_cleared`, `paid_promotion_declared`, `rights_review`, `scene_evidence`, `signed_human_approval`, `synthetic_disclosure`, `technical_qa`, `transformation_note`, `upload_audit_log`, `verified_source`, `vod_rights_confirmed`

Note: `required_gates` is a policy/documentation list. The enforced set is `compliance.CHECKS` plus the signed-log requirements above.
