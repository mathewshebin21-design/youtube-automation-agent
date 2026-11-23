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
- **Daily cap is hard-capped at 1.** The effective cap is `min(CUTSCENECITY_DAILY_CAP or policy daily_upload_cap, 1)`, in both Python and Node. A value of 0, a negative value or anything unparseable blocks all uploads (fail closed).
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
