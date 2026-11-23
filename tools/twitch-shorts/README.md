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
- **Daily cap is hard-capped at 2** (raised from 1 in Phase 2.5). The effective cap is `min(CUTSCENECITY_DAILY_CAP or policy daily_upload_cap, 2)`, in both Python and Node; the policy default is 2. Values above 2 clamp to 2. A value of 0, a negative value or anything unparseable blocks all uploads (fail closed). Attempts are counted per **IST calendar day (UTC+05:30, midnight to midnight)** from the shared ledger.
- **New required human check: `overlays_third_parties_cleared`.** It confirms that chat, alerts and usernames are blurred in the final render, that no viewer TTS or donation messages can be heard, and that no guest or voice-chat audio is in the mix.
  - `review.py precheck` now runs `overlay_scan.py` on the final render. It uses edge density (OpenCV) plus tesseract OCR when installed. OCR text is never stored, only counts and boxes.
  - The scan only flags. When it flags something, or can't run, the sign-off needs a note of 5+ words.
  - The sign-off is refused unless the scan matches the current file hash. The uploader and the Node route re-check it.
- **Paid promotion.** `review.py paid --value none|present --by NAME` writes a signed declaration that's bound to the file hash and recorded in the approval.
  - The upload always sends `paidProductPlacementDetails.hasPaidProductPlacement` explicitly: `false` for none, `true` for present, with part `snippet,status,paidProductPlacementDetails`.
  - If the declaration is missing, approve, export, the uploader and the Node route all block.
- Package schema is now `cutscenecity.upload-package/4`. The agent import gains `paidProductPlacement`.
- **Owner default:** `owner_twitch_login: "cutscenecity"` in `editorial-policy.json`, and `.env.example` sets `CUTSCENECITY_OWNER_TWITCH_LOGIN=cutscenecity`. The env value overrides the policy; if both are empty, every VOD is rejected (fail closed). Only cutscenecity VODs pass, which also lets the CI candidate step run.
- **Game audio is kept by default.** Background music, game voices and story/cutscene scenes stay in the clip unchanged; nothing strips, mutes or ducks them, and no step drops cutscene segments (`no_story_cutscene` is a human sign-off only).
  - `review.py commentary` mixes game + mic (1.0) + voiceover in `mix` mode.
  - `--music-volume` or `CUTSCENECITY_MUSIC_VOLUME` (default 1.0 = unchanged; must be above 0 and at most 1) lowers the game bed after review.
  - `--strip-game-audio` (the old `mic_stem`) is opt-in.
  - loudnorm is overall loudness only.
  - With OBS multitrack, put game/desktop audio on track 1 without the mic, so the mic isn't doubled.
  - Licensed in-game radio music may trigger Content ID claims, so review it before any upload. `music_risk_cleared` still needs the fingerprint pre-check and a note.

## OBS audio setup and the mixed-track path (Phase 2.3)
- **OBS Twitch VOD Track.** In OBS, **track 1 is the live audio feed and track 2 is the VOD audio feed** by default. A source left off track 2 isn't in the Twitch VOD. Tracks 3-6 stay free for separating audio for editing. The setting is Settings → Output → Twitch VOD Track, and your Twitch account must be connected under Settings → Stream. (VERIFIED: OBS knowledge base, "Twitch VOD Track Guide", obsproject.com/kb/twitch-vod-track-guide.)
  - CutsceneCity routing: track 1 = live mix; track 2 (Twitch VOD Track) = mic + game + story audio, all kept.
- **A downloaded Twitch VOD still has ONE mixed audio track.** The VOD Track only chooses *what* goes into the VOD; the mic isn't stored separately. VOD 2937578726 probes as 1 video + 1 stereo audio stream (checked with ffprobe here). Commentary therefore can't be measured from the VOD.
- **For the best gate results, also keep a local OBS recording with the mic on its own track.** Set Settings → Output → Recording → Audio Track to tick e.g. 1 + 3, and put only the mic on track 3. Then run `review.py commentary --clip <clip> --mic-stream N` with the 0-based audio index; the measured mic path is preferred automatically.
- **Mixed-track path (no mic stem; creator-owned VODs only).** `original_commentary` and `live_reaction_preserved` show **WARN**, not FAIL. They pass only after a signed `review.py signoff --check mixed_track_commentary_confirmed --by NAME --note "<5+ words: live commentary audible>"`.
  - The manifest records `commentary_source: mic_stem | mixed_track_signed`.
  - The voice-band "speech share" (`mixed_track_speech_share`) is a hint only. Game voices, cutscene dialogue and music count too; on VOD 2937578726 it reads 100% for every clip.
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

## Daily cap 2 (Phase 2.5)

- Shebin approved raising the cap from 1 to 2 uploads per day. The hard clamp is `min(cap, 2)` in `gatelog.py` and `external-shorts.js`, and `daily_upload_cap` defaults to 2 in `editorial-policy.json` and `.env.example`.
- Unchanged: 0, negative or unreadable values block all uploads; values above 2 clamp to 2; the day boundary is the IST calendar day (UTC+05:30); every upload is still private-only and needs its own human approval; `upload_private.py` and the Node route both re-check the cap and duplicates against the shared ledger.
