# CutsceneCity Twitch → Shorts integration (review-only prototype)

Source: your own CutsceneCity Twitch VODs only (no default VOD; pass --url explicitly).
Destination: YouTube CutsceneCity (@cutscenecity), connected separately through vidIQ.

Run GitHub Actions workflow **CutsceneCity Twitch VOD Shorts (review only)** manually after merging this PR. The job downloads your own VOD with yt-dlp, ranks candidate windows, renders 9:16 MP4s and uploads review artifacts (manifest + clips, 3-day retention). It does **not** upload to YouTube, schedule videos, or enable autonomous external actions.

## Limitations and release gates
- Motion is not semantic understanding: a human must watch and approve each selected scene.
- VOD playback/download can fail due to Twitch availability, age gates, authentication or restrictions.
- GitHub Actions hosted runners have storage, time and artifact size limits; a one-hour VOD may exceed them.
- Original broadcast rights do not automatically grant game publisher or music rights.
- Default layout `blur` keeps the full frame (HUD and action) over a blurred fill; no destructive crop unless you choose one.
- Before connecting this to the existing YouTube agent publishing pipeline: validate real clips, review game/music rights, confirm channel OAuth scope, obtain approval for exact media and metadata, and test a private upload.
- Never commit Twitch cookies, OAuth tokens, Google credentials or large VOD files.

## Phase 1 tweaks (local branch `cutscenecity-phase1-tweaks`, not merged)
- Selection: motion + audio loudness peaks + optional chat velocity (`--chat`) + transcript keywords (`--transcript`); every candidate gets a `selection_note`.
- Layouts: `--layout pad|blur|crop|split` (`--crop-x 0..1|smart`, `--facecam-box x,y,w,h`), `--captions` (faster-whisper if installed), loudnorm -14 LUFS.
- Default-deny compliance gates (`compliance.py`), signed review log (`gatelog.py`), review CLI (`review.py`), gated PRIVATE uploader (`upload_private.py`, local only, dry run by default).
- CI stays review-only: the workflow never installs upload libraries or touches YouTube credentials.
- Full guide: `CUTSCENECITY-PHASE1.md` in the patch folder handed to the creator.

## Phase 2.1 / Gate 4 v3 (creator-owned + commentary rules)
- **Gate 1, creator-owned only.** Set `CUTSCENECITY_OWNER_TWITCH_LOGIN` (recommended) and/or `CUTSCENECITY_OWNER_TWITCH_ID` in your shell, never in the repo. `pipeline.py` reads `yt-dlp -J` metadata **before downloading** and refuses any VOD whose `uploader_id`/`channel`/`channel_id` is not the owner. It fails closed if the owner is unset, the channel is unknown, or only a display name is present. Twitch metadata usually has no numeric `channel_id`, so an ID-only setup always fails; set the LOGIN. The third-party licence path is gone. For `--input` files, pass `--info-json vod.info.json`.
  - CI note: the review-only workflow does not pass these variables, so its pipeline step now stops at the owner check (fail closed) until the workflow exports `CUTSCENECITY_OWNER_TWITCH_LOGIN`.
- **Commentary of at least 60%, measured on live mic + TTS** (`CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY`, default `true`). Any TTS forces `containsSyntheticMedia=true`.
- **Live reaction is never muted or ducked.** The render uses `audio_mode=mic_stem`: the creator's mic plays at gain 1.0, game/music audio is dropped, and the mix is loudnormed. A Twitch VOD has **one mixed audio track**, so the mic cannot be separated from it. You need an OBS multitrack recording (`--mic-stream N`) or a separate mic file on the VOD timeline (`--mic file`). Without either, `commentary` refuses (fail closed). Stem separation is not built.
- **Script.** `review.py script --file script.txt --by NAME [--note ...]` is required when TTS is used and is signed in the review log. It is compared against the last 30 scripts (`$CUTSCENECITY_STATE_DIR/script-history.jsonl`) using 3-word-shingle Jaccard: 40% or more needs a reviewer note, above 50% is rejected, and a reused opener or closing/CTA line (exact, or 80% or more word overlap) is rejected.
- **Rotation.** `--voice-preset` and `--caption-style` must come from `editorial-policy.json` and must differ from the previous upload's (read from the shared upload ledger).
- **Blur regions per stream-layout profile.** Use `--profile NAME`; the default comes from `default_layout_profile`. Each profile sets `facecam_box` and `blur_regions` as fractions of the source frame.
- Example: `review.py commentary --mic-stream 1 --audio vo.wav --tts --voice-preset puck-hyped --caption-style yellow-pop --captions`

## Phase 2.2 (blocking fixes)
- **Daily cap is hard-capped at 2** (raised from 1 in Phase 2.5). The effective cap is `min(CUTSCENECITY_DAILY_CAP or policy daily_upload_cap, 2)`, in both Python and Node; the policy default is 2. Values above 2 clamp to 2. A value of 0, a negative value or anything unparseable blocks all uploads (fail closed). Attempts are counted per **IST calendar day (UTC+05:30, midnight to midnight)** from the shared ledger. **(Superseded in Phase 2.7: hard cap 1, see below.)**
- **New required human check: `overlays_third_parties_cleared`.** It confirms that chat, alerts and usernames are blurred in the final render, that no viewer TTS or donation messages can be heard, and that no guest or voice-chat audio is in the mix.
  - `review.py precheck` now runs `overlay_scan.py` on the final render. It uses edge density (OpenCV) plus tesseract OCR when installed. OCR text is never stored, only counts and boxes.
  - The scan only flags. When it flags something, or can't run, the sign-off needs a note of 5+ words.
  - The sign-off is refused unless the scan matches the current file hash. The uploader and the Node route re-check it.
- **Paid promotion.** `review.py paid --value none|present --by NAME` writes a signed declaration that's bound to the file hash and recorded in the approval.
  - The upload always sends `paidProductPlacementDetails.hasPaidProductPlacement` explicitly: `false` for none, `true` for present, with part `snippet,status,paidProductPlacementDetails`.
  - If the declaration is missing, approve, export, the uploader and the Node route all block.
- Package schema is now `cutscenecity.upload-package/4`. The agent import gains `paidProductPlacement`.
- **Owner default:** `owner_twitch_login: "cutscenecity"` in `editorial-policy.json`, and `.env.example` sets `CUTSCENECITY_OWNER_TWITCH_LOGIN=cutscenecity`. The env value overrides the policy; if both are empty, every VOD is rejected (fail closed). Only cutscenecity VODs pass, which also lets the CI candidate step run.
- **Game audio is kept by default.** Background music, game voices and story/cutscene scenes stay in the clip unchanged; nothing strips, mutes or ducks them, and no step drops cutscene segments (`no_story_cutscene` is a human sign-off only). **(Superseded in Phase 2.7: game audio is stripped by default; keeping it is opt-in with `--keep-game-audio`.)**
  - `review.py commentary` mixes game + mic (1.0) + voiceover in `mix` mode.
  - `--music-volume` or `CUTSCENECITY_MUSIC_VOLUME` (default 1.0 = unchanged; must be above 0 and at most 1) lowers the game bed after review.
  - `--strip-game-audio` (the old `mic_stem`) is opt-in. (Phase 2.7 made stripping the default and the flag a no-op; the Phase 2.8 override made game audio kept by default again, so `--strip-game-audio` is the opt-in once more.)
  - loudnorm is overall loudness only.
  - With OBS multitrack, put game/desktop audio on track 1 without the mic, so the mic isn't doubled.
  - Licensed in-game radio music may trigger Content ID claims, so review it before any upload. `music_risk_cleared` still needs the fingerprint pre-check and a note.

## OBS audio setup and the mixed-track path (Phase 2.3; the mixed-track path was removed in Phase 2.8)
- **OBS Twitch VOD Track.** In OBS, **track 1 is the live audio feed and track 2 is the VOD audio feed** by default. A source left off track 2 isn't in the Twitch VOD. Tracks 3-6 stay free for separating audio for editing. The setting is Settings → Output → Twitch VOD Track, and your Twitch account must be connected under Settings → Stream. (VERIFIED: OBS knowledge base, "Twitch VOD Track Guide", obsproject.com/kb/twitch-vod-track-guide.)
  - CutsceneCity routing: track 1 = live mix; track 2 (Twitch VOD Track) = mic + game + story audio, all kept.
- **A downloaded Twitch VOD still has ONE mixed audio track.** The VOD Track only chooses *what* goes into the VOD; the mic isn't stored separately. VOD <VOD_ID> probes as 1 video + 1 stereo audio stream (checked with ffprobe here). Commentary therefore can't be measured from the VOD.
- **For the best gate results, also keep a local OBS recording with the mic on its own track.** Set Settings → Output → Recording → Audio Track to tick e.g. 1 + 3, and put only the mic on track 3. Then run `review.py commentary --clip <clip> --mic-stream N` with the 0-based audio index. Since phase 2.8 this mic stem is required (there is no mixed-track path).
- **Mixed-track path: REMOVED (phase 2.8).** Phase 2.3 let a clip with no mic stem pass on a signed `mixed_track_commentary_confirmed`; phase 2.7 turned that off by default and phase 2.8 deleted it, together with `CUTSCENECITY_ALLOW_MIXED_TRACK`, policy `mixed_track_path_enabled`, `commentary_source: mixed_track_signed` and the `mixed_track_speech_share` hint. A clip without a separate creator mic stem now always FAILs `original_commentary` and `live_reaction_preserved` (Python, `upload_private.verify_package`, Node). Phase 2.8.1 adds a live-voice floor: the mic stem alone must cover at least 30% of the runtime.
  - Non-owner VODs are still rejected.
- **Music in the VOD track.** Twitch scans VODs and clips for copyrighted audio and mutes the matching VOD portions and deletes matching clips (VERIFIED: Twitch Help, "Copyrighted Audio Detection & Warnings"). Licensed music, such as in-game radio, may also get YouTube Content ID claims on the Short (UNVERIFIED this pass: standard Content ID behaviour, YouTube docs not re-checked).
- UNVERIFIED (community reports only, not official docs): Twitch Enhanced Broadcasting or a third-party "soundtrack" plugin can override the VOD Track routing. Check one test VOD after any OBS change.
- **Automatic now:** `qa.py` runs at the end of `--render`. The description starts with a factual credit line built from info.json: `From my Twitch stream: https://www.twitch.tv/<login> — full VOD: <url>`. `containsSyntheticMedia` is filled in automatically (true if TTS/AI voice/visuals are used, else false), with the reason recorded.
  - `paid_promotion` is only *suggested* (`none`) in `status`; it still has to be signed with `review.py paid`.
  - Title, your description text and the transformation note are never generated. `review.py status` lists what's missing and the command for each.

## Upscale step (Phase 2.4, ON by default)

- Every `--render` upscales the captioned 1080x1920 output to **2160x3840 by default**. Choose `--upscale 1440|2160|off` (flag), or set `CUTSCENECITY_UPSCALE` (the flag wins over the env var). Use `off` only for tests and debugging; the test suite sets `CUTSCENECITY_UPSCALE=off` so it stays fast.
- Order: ffmpeg render + captions → **upscale** → `qa.py` → overlay scan / `review.py precheck` → export SHA-256. QA, the overlay scan, precheck and the package hash all cover the final upscaled file.
- Method: ffmpeg `scale=W:H:flags=lanczos,unsharp=5:5:0.5:5:5:0.0`, libx264 preset medium, CRF 18, yuv420p, `+faststart`. The audio stream is copied unchanged (`-c:a copy`). The file is replaced in place through a temp file.
- It never upscales past the target. If the source is already at or above the target, the step is skipped and `render.upscale` records `skipped (...)`.
- **Honest note:** upscaling a 1080p source adds **no real detail**. The only benefit is that YouTube serves a 2160p upload with its higher-bitrate encode (VP9/AV1 4K ladder), which usually looks cleaner on phones than the 1080p encode.
- Measured on a 35 s 1080x1920 clip (8 vCPU box): about **+54 s** render time, and the file grew from **17.6 MB to 67.1 MB** (~3.8x, ~15 Mb/s). Audio MD5 was unchanged and qa passed.
- The Node route (`POST /api/gta6/external-shorts`) and `upload_private.py` accept 1080x1920, 1440x2560 and 2160x3840. The Node route rejects any other `render.upscale` value or output resolution.
- Re-render with the commentary stem: `review.py commentary ... --upscale 2160` (default) or `--upscale off`.

## Daily cap 2 (Phase 2.5; superseded by Phase 2.7: cap 1)

- Shebin approved raising the cap from 1 to 2 uploads per day. The hard clamp is `min(cap, 2)` in `gatelog.py` and `external-shorts.js`, and `daily_upload_cap` defaults to 2 in `editorial-policy.json` and `.env.example`. **(Phase 2.7: reverted to a hard cap of 1, see below.)**
- Unchanged: 0, negative or unreadable values block all uploads; values above 2 clamp to 2; the day boundary is the IST calendar day (UTC+05:30); every upload is still private-only and needs its own human approval; `upload_private.py` and the Node route both re-check the cap and duplicates against the shared ledger.

## Edit stage: captions, animations and effects (Phase 2.6; defaults and gates changed in Phase 2.7, see below)

- `--edit-style off|clean|hype` on `pipeline.py --render` and `review.py commentary`, or env `CUTSCENECITY_EDIT_STYLE`. **2.6 default was `hype`; 2.7 changes it (below).** `clean` = word-by-word captions only. `off` = no edit pass (the old `--captions` SRT path still works); the test suite sets `CUTSCENECITY_EDIT_STYLE=off` to stay fast.
- Order: ffmpeg render (layout, blur regions, audio mix + loudnorm) → **edit (captions/effects)** → upscale (default 2160x3840) → `qa.py` → overlay scan / `review.py precheck` → export SHA-256. The package SHA binds the final edited + upscaled file.
- ffmpeg + libass only (`tools/twitch-shorts/edit.py`). No paid services, stock assets, added music or SFX. The edit pass copies the audio stream (`-c:a copy`), so the original audio and `--music-volume` are untouched.
- **Word-by-word captions:** faster-whisper word timestamps (`CUTSCENECITY_WHISPER_MODEL`, default `small`; a local model path works). ASS events reveal the words of a 1-3 word group one by one; the current word pops in (130% → 100% over 120 ms) and is highlighted. Bold white Liberation Sans, black outline, MarginV 360 px (above the bottom 15% of 1920). Captions are the exact transcribed words; only ASS control characters `\ { }` are dropped. Swear words are kept as said. Files: `short_NN.words.ass`, `short_NN.words.json`. Transcription is two-pass: Silero VAD (threshold 0.25) first; only if that finds no words, a no-VAD pass whose low-confidence (avg_logprob < -1.0, no_speech_prob > 0.6, compression > 2.4) and repeated segments are dropped, never rewritten (`render.transcribe_mode`). On mixed-track VODs with loud game audio, whisper often hears only a few lines, so captions can be sparse and may contain mishearings: they stay `..._NEEDS_HUMAN_CHECK`. If faster-whisper is missing or no speech is found, captions are skipped and recorded.
- Caption highlight styles live in `editorial-policy.json` `word_caption_styles` (`word-pop-yellow` default, `word-pop-cyan`, `word-pop-green`; choose with `--caption-style`). Burned word captions set `render.captions = BURNED_WORD_BY_WORD_NEEDS_HUMAN_CHECK`, so the existing caption-style rotation gate (Python and Node) applies: the style must be in the policy and may not repeat the previous upload.
- **hype effects:**
  - Punch-in zoom ~1.15x (zoompan expression, smoothstep ease in 0.3 s, hold 0.5 s, ease out 0.3 s) on audio-energy spikes: ≥ 4.5 dB above the median of the previous 3 s, measured on the ORIGINAL source audio (loudnorm flattens spikes), strongest first, never closer than 4 s (max 1 per 4 s). A 0.2 s shake (±10 px) on the top 1-2 spikes.
  - Hook: 1.1 → 1.0 zoom-out over the first 0.5 s. 0.3 s video fade-out at the end (audio not faded).
  - Thin progress bar (10 px, white) along the bottom edge.
  - Flash cut: `--join-adjacent` joins two picks that touch end-to-start into one clip (≤ 60 s); `--flash-cut` adds a 0.16 s white flash at that join. Both off by default.
- `render` records `edit_style`, `zoom_count`, `punch_ins`, `shake_at`, `word_captions`, `word_count`, `edit_seconds`.
- `--window START-END` (repeatable) renders exact windows (seconds in the input file) instead of auto-selection.
- The transformation note stays Shebin's own text; nothing here writes it.

## Phase 2.7: Compliance fixes to the edit stage (local branch `cutscenecity-phase2.7-compliance`)
The 2.6 hype default stays recoverable on commit 02c223c. Shared rules live in `edit_gates.py`; the Node gate re-checks them on its own.
1. **No automatic edit.** `pipeline.py --render` renders the PRE-EDIT clip only. `--edit-style clean|hype`, `--captions`, `--caption-style` and `--flash-cut` on `pipeline.py` are refused, with a pointer to `review.py edit`. An edit style without a recorded human choice raises an error, including when it comes from env `CUTSCENECITY_EDIT_STYLE`.
2. **Captions only from a mic stem.** Captions come from an OBS multitrack mic stream (`--mic-stream N`) or a mic file (`--mic`) and nothing else. If the clip only has the mixed Twitch/game track, the captions effect is refused with a clear error (`CaptionSourceError`), and the Node gate rejects any `caption_source` that is not `mic_*`. The old SRT `--captions` path is removed.
3. **`captions_reviewed` human gate** (Python `compliance.py` and Node `external-shorts.js`). It applies when captions are burned in.
   - `review.py signoff --check captions_reviewed` checks that `short_NN.words.json` still matches the SHA-256 recorded at render time, and puts `words_json_sha256` in the signed log entry.
   - approve, export, `upload_private` and Node ingest all require that signed entry, for this exact final file and this exact words.json. The package carries `captions.words.json` plus a `captions` block.
4. **Profanity.** Words matching `editorial-policy.json` `caption_policy.profanity_terms` (as a case-insensitive prefix) are masked as first letter + `*` (`f******`) in words.json and the ASS file, and marked `masked: true`.
   - Profanity in the first 10 s is flagged, and a flagged caption review needs a note of 5+ words.
   - Unmasked profanity blocks the clip.
   - **LIMITATION: the audio is NOT bleeped**; a human decides about the spoken words.
5. **Spoiler/keyword scan on the caption text.** It matches `caption_policy.story_names` and `plot_keywords`, plus the shared `spoiler-defaults.json` and `spoiler-keywords.txt` lists, as whole tokens, including multi-word terms.
   - Hits are flagged and need a note of 5+ words.
   - The lists are seeded with Lucia and Jason (publicly announced protagonists) plus `PLACEHOLDER_*` entries. **Shebin/Compliance must fill these in**; until then every caption review is flagged as `keyword_list_incomplete`.
6. **Overlay precheck scans the pre-edit render.** Every edit keeps `short_NN.preedit.mp4` (1080x1920, before captions/effects) with its SHA-256. `review.py precheck` scans that file, so our own captions can't trigger flags, and binds the result to the FINAL file hash. If the pre-edit file is missing or stale, it scans the final file with the caption band (0.66–0.84 of the height) and the progress bar masked.
7. **Edit style + effects are a per-clip human choice.**
   - Command: `review.py edit --clip short_01.mp4 --style clean|hype --effects captions,punch_in,shake,hook_zoom,end_fade,progress_bar,flash_cut --by NAME [--caption-style word-pop-cyan] [--flash-intensity 0.5] [--no-render]`.
   - It signs an `edit_choice` log entry (style, effects, flash %, caption style, reviewer) and re-renders with the clip's previous audio setup. `review.py commentary` re-renders reuse it.
   - `clean` allows only `captions`.
   - The `style_rotation` gate (Python and Node) fails when the render's style or effects differ from the recorded choice or no choice exists. approve, export, upload and ingest also require the signed entry.
8. **Flash cut** is off unless `flash_cut` is chosen: at most 1 per clip, intensity ≤ 0.5 (default 0.5), hard limits in `edit_gates.py`/`edit.py` and the Node gate.

The render records `edit_style`, `edit_effects`, `edit_choice_by`, `caption_source`, `words_json`, `words_json_sha256`, `caption_review` (flags + warnings), `pre_edit_file`, `pre_edit_sha256`, `flash_cuts` and `flash_intensity`.

## Phase 2.7 defaults (Compliance; separate commit on the same branch)
- **Game audio is stripped by default.** (Superseded by the Phase 2.8 override below: game audio is KEPT by default again.) `review.py commentary` renders `audio_mode=mic_stem` (mic + optional voiceover only). Keeping game/music audio is opt-in per render with `--keep-game-audio` (`audio_mode=mix`, recorded as `render.keep_game_audio_opt_in: true`). `render.render(audio_mode="mix")` without the opt-in raises an error. Python `live_reaction_preserved` and the Node gate fail a `mix` render that has no opt-in. (In 2.7 `--strip-game-audio` was accepted as a no-op; since the Phase 2.8 override it is the opt-in that strips game audio.)
- **A separate mic track is required.** Phase 2.7 turned the mixed-track path off by default (it still had an env/policy opt-in then); phase 2.8 removed the path and the opt-in entirely, so there is nothing to opt in to.
- **Hard daily cap 1** (back from 2), in `gatelog.py`, `external-shorts.js`, the `editorial-policy.json` `daily_upload_cap` and `.env.example`. The existing `CUTSCENECITY_DAILY_CAP` override is kept; it can lower the cap or set it to 0, but values above 1 clamp to 1. Days are still counted in IST.
- **Default edit style `clean`; `hype` is opt-in.**
  - `review.py edit --by NAME` with no `--style`/`--effects` records the default choice `clean` + `captions`, which needs a mic stem.
  - `hype` needs `--style hype --effects ...`.
  - Nothing is edited until a human records the choice (fix 7): renders without a recorded choice stay pre-edit, and an explicit or env `CUTSCENECITY_EDIT_STYLE` style without a choice is refused.

## Phase 2.8: Compliance conditional pass (local branch `cutscenecity-phase2.8`)
- **(A) Mixed-track bypass removed entirely.** `CUTSCENECITY_ALLOW_MIXED_TRACK` and policy `mixed_track_path_enabled` are gone and no longer read; the `mixed_track_commentary_confirmed` check is deleted. A clip without a separate creator mic stem always FAILs `original_commentary` (60% measured on the mic stem) and `live_reaction_preserved` in `compliance.py`, `upload_private.verify_package` and the Node gate. The phase 2.3 / 2.7 mixed-track text above is superseded.
- **(C) First render** (as first committed: `audio_mode=mic_stem`; changed by the override below to keep game audio). `pipeline.py --mic-stream N` (OBS multitrack recording) or `--mic FILE` renders the mic stem straight away. With neither, pipeline prints a notice and renders a **silent preview** (`audio_mode=none`, video only, no VOD audio). It fails `technical_qa`, `original_commentary` and `live_reaction_preserved` by design until `review.py commentary --mic-stream N|--mic FILE`. The manifest records `first_render_audio`.
- **(D) Audio profanity gate (Python + Node).**
  - `review.py edit --by NAME` (any style, including `--style off --effects none`) on a mic-stem render scans the mic stem transcript (faster-whisper word timestamps; the captions transcript is reused) for `caption_policy.profanity_terms` and stores `render.profanity_audio` (masked words, int ms). Without faster-whisper the record says `UNAVAILABLE_NO_FASTER_WHISPER` and the clip fails closed.
  - Optional bleep: `--bleep tone` (1 kHz tone) or `--bleep mute` over each flagged word +/-50 ms; default `off`. The bleep is part of the signed per-clip edit choice. In `mix` renders the bleep also silences the game audio over the word.
  - Strong profanity in the first 10 s blocks the clip unless bleeped.
  - New required human check `profanity_audio_reviewed`, signed with `final_sha256` and `profanity_audio_sha256` (pinned to the exact final file and scan); a 5+ word note when anything was found.
  - New auto check `title_thumbnail_profanity_free`: `metadata.title` and `metadata.thumbnail_text` against the same list.
- **(E) `music_risk_cleared` wording fixed** to match the current default (see the override below): game audio is kept, so licensed radio/score is a real Content ID risk and the whole clip must be listened to.
- Real VOD ids in docs and this README are replaced by `<VOD_ID>`.
- Limitations: obfuscated spellings (`f*ck`) and words whisper mishears are not caught; the bleep needs faster-whisper; a first render without a mic stem (silent preview as first committed, source audio after the override below) is not uploadable.

## Phase 2.8.1: Compliance conditional-pass fixes (local, branch `cutscenecity-phase2.8`)
- **Live-voice floor.** `original_commentary` now also needs the creator's live voice, measured on the mic stem ONLY (`speech_seconds_live`), to cover at least 30% of the runtime (`min_live_voice_coverage`, which policy may only raise). TTS/voiceover can top the total up to 60% but cannot replace the creator: 20% mic + 50% TTS FAILs, 35% mic + 30% TTS PASSes. Game audio + TTS with no mic stays a hard FAIL. Enforced in `compliance.py`, independently in `upload_private.verify_package`, and in the Node gate.
- **Music note re-checked independently.** Whenever `audio_mode` is `mix` or `source`, `upload_private.verify_package` and Node ingest each require the latest signed `music_risk_cleared` sign-off for the exact file to carry a 5+ word note (they don't rely on Python's WARN hint).
- **Full-mix profanity coverage (both chosen).** `review.py edit` now also transcribes the FULL final mix (game dialogue, voiceover and mic) and scans it (`profanity_audio.mix_hits`, `mix_status`); bleep segments cover mic and mix hits; an unbleeped hit in the first 10 s of either blocks; a missing or unavailable full-mix scan fails closed. Because whisper is unreliable on dialogue under music and game noise, the `profanity_audio_reviewed` sign-off ALSO has to record a human confirmation: `review.py signoff --check profanity_audio_reviewed --first-10s-full-mix-checked ...` (signed field `first_10s_full_mix_checked: true`), checked by `signed_problems` (approve, export, verify_package) and by Node ingest.
- Stale mixed-track text in this README and `docs/cutscenecity/CUTSCENECITY-PHASE1.md` rewritten.

## Phase 2.8 override: game audio KEPT by default (Shebin, 9:24 AM IST: "Do NOT strip game audio. Keep the original game audio and add a voiceover on top of it.")
- Upload renders are `audio_mode=mix`: original game audio (music volume default 1.0, unchanged) + the separate creator mic stem at gain 1.0 + an optional voiceover/TTS on top (`review.py commentary --audio VOICE [--tts --voice-preset P]`); no ducking, loudnorm on the whole mix only.
- `pipeline.py --mic-stream N` / `--mic FILE` renders `mix` straight away; without a mic it renders the source audio (`audio_mode=source`), which fails `original_commentary` / `live_reaction_preserved` until the mic stem is added.
- Stripping game audio is opt-in: `review.py commentary --strip-game-audio` (`mic_stem`). `--keep-game-audio` is accepted as a no-op. Policy `game_audio_default: "kept"`; the `keep_game_audio_opt_in` field and its gate are gone in Python and Node (render records `game_audio` and `strip_game_audio_opt_in`).
- Unchanged: the separate mic stem is still required for the 60% measurement and captions (no mixed-track bypass), plus `captions_reviewed` and the audio-profanity gate. `review.py commentary --audio VOICE` without a mic renders game + voiceover for review only; both commentary gates FAIL.
- `music_risk_cleared`: kept game audio may include licensed in-game radio or score, so the hint is always WARN on a kept-audio render; a whole-clip listen + 5+ word note is required, the fingerprint pre-check is a local hint (not Content ID). Licensed music audible: `--strip-game-audio` or another window.
- Phase 2.8.1 applies on top: with game audio kept, Node and `verify_package` re-check the 5+ word `music_risk_cleared` note themselves, and the full-mix profanity scan covers in-game dialogue.
