# CutsceneCity gate list (generated from code, branch `cutscenecity-phase2.7-compliance`)

Generated from `tools/twitch-shorts/compliance.py` (`compliance.CHECKS`, 18 registered checks). Every check starts as PENDING, and only PASS unblocks it (default-deny).
- `auto` checks are computed from the manifest and media.
- `human` checks need `review.py signoff --check NAME --by NAME [--note ...]`, which is signed into the HMAC review log and bound to the final file's SHA-256. A WARN hint needs a note of 5+ words; a FAIL hint blocks the sign-off.

| Gate | Kind | What it requires |
|---|---|---|
| `creator_owned_source` | auto | Source VOD belongs to the configured owner channel (yt-dlp metadata vs CUTSCENECITY_OWNER_TWITCH_LOGIN / CUTSCENECITY_OWNER_TWITCH_ID). No third-party sources. |
| `vod_rights_confirmed` | human | A person confirms the VOD is from their own channel and the provenance record is true. |
| `no_story_cutscene` | human | A person confirms the clip is player gameplay, not a story cutscene (Rockstar story content). |
| `music_risk_cleared` | human | Game audio is kept by default (mix, music volume adjustable); a person listens for licensed music/radio (Content ID risk) and signs off; fingerprint pre-check result attached. |
| `overlays_third_parties_cleared` | human | A person confirms chat, alert and username regions are blurred in the FINAL render, no viewer TTS/donation messages are audible, and no guest or voice-chat audio is in the mix. |
| `captions_reviewed` | human | A person read the burned captions (the exact words.json, SHA-256 bound) against the final file: words are right, strong profanity is masked (audio is NOT bleeped), no story names or plot dialogue. |
| `paid_promotion_declared` | auto | Reviewer declared paid_promotion as none or present (signed); sent explicitly on upload. |
| `mixed_track_commentary_confirmed` | human | Mixed-track path (no mic stem; Twitch VOD has one mixed track): a person listened to the whole clip and confirms the creator's live commentary is clearly audible over the game audio. Note of 5+ words required. |
| `original_commentary` | auto | Creator mic + voiceover/TTS (energy VAD on the combined commentary bus) covers at least 60% of runtime. TTS counts only when CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY is on (default) and containsSyntheticMedia is true. |
| `live_reaction_preserved` | auto | The creator's real mic/reaction track is in the final mix at full level (never muted or ducked). |
| `commentary_script` | auto | When TTS is used: a human-edited script is stored and approved in the signed review log (review.py script). |
| `script_originality` | auto | Script vs the last 30 approved/uploaded scripts: flag at 40% shingle overlap (needs a reviewer note), reject above 50%; any reused opener or CTA line is rejected. |
| `style_rotation` | auto | Voice preset (when TTS) and caption style come from the policy lists and differ from the previous upload; edit style + effects match the per-clip human edit choice; flash cut <= 1 per clip at <= 0.5 intensity. |
| `attribution` | auto | Source streamer name and Twitch VOD URL present in description. |
| `transformation_note` | auto | Reviewer wrote what this Short adds (commentary, context, edit) in at least 25 words. |
| `metadata_spoiler_free` | auto | Title, description and tags contain no spoiler keywords. |
| `synthetic_disclosure` | auto | containsSyntheticMedia is true whenever TTS or AI visuals are used. |
| `technical_qa` | auto | qa.py technical checks passed on the final render. |

## Extra signed-log requirements (review.py approve/export, upload_private.verify_package, Node ingest)
- `paid_promotion`: a signed `review.py paid --value none|present` for this exact file.
- `overlay_scan`: run on this exact final file (phase 2.7 scans the pre-edit render, see fix 6).
- `commentary_script`: a signed script approval when TTS or a script is used.
- `edit_choice` (phase 2.7): a signed per-clip human choice of style and effects whenever an edit was applied.
- `captions_reviewed` (phase 2.7): the signed sign-off carries `words_json_sha256` of the exact words.json; the package ships `captions.words.json`.
- `approve`: a signed approval of the exact file, metadata, provenance, script hash and paid value.
- Daily cap: hard maximum 1 per IST day (env `CUTSCENECITY_DAILY_CAP` can only lower it). There is a duplicate/overlap check against the upload ledger. Uploads are private only.

## Node (`utils/cutscenecity/external-shorts.js`)
`checkClipGates` and the ingest verification re-check the gates independently and never trust the statuses Python saved:
- creator-owned source, attribution, spoilers, synthetic disclosure, resolution;
- mic stem / mixed-track opt-in, keep-game-audio opt-in, 60% commentary, script reuse, rotation;
- the edit choice, flash limits, mic-only captions and the words.json review;
- all compliance statuses PASS.
`REQUIRED_HUMAN_CHECKS` = `vod_rights_confirmed`, `no_story_cutscene`, `music_risk_cleared`, `overlays_third_parties_cleared`, plus policy `extra_human_checks`, `mixed_track_commentary_confirmed` (mixed path) and `captions_reviewed` (burned captions).

## Policy `required_gates` list (editorial-policy.json)
`attribution`, `audio_quality`, `caption_accuracy`, `creator_owned_source`, `daily_cap`, `deduplication`, `duplicate_check`, `human_approval`, `media_decode`, `metadata_spoiler_free`, `music_risk_cleared`, `no_story_cutscene`, `original_commentary`, `overlays_third_parties_cleared`, `paid_promotion_declared`, `rights_review`, `scene_evidence`, `signed_human_approval`, `synthetic_disclosure`, `technical_qa`, `transformation_note`, `upload_audit_log`, `verified_source`, `vod_rights_confirmed`

Note: `required_gates` is a policy/documentation list. The enforced set is `compliance.CHECKS` plus the signed-log requirements above.
