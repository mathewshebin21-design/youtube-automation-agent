# CutsceneCity Phase 1 + Phase 2: audit of PR #1 and local tweaks

> Phase 2 (below, §8) changes some Phase 1 defaults:
> - own VODs only, and no default VOD;
> - TTS counts toward the 60% rule but forces the AI disclosure;
> - CI artifact step left as in the PR;
> - daily cap 1 (raised to 2 in Phase 2.5, §13);
> - default layout blur;
> - new Node ingest route;
> - audit package.
>
> Where Phase 1 text disagrees, §8 wins.

- **Base:** `origin/feature/cutscenecity-twitch-vod-shorts` @ `8cbb605` (draft PR #1, based on `master` @ `e973d51`).
- **Local branch:** `cutscenecity-phase1-tweaks` @ `ccad4e8`. This branch is NOT pushed. It is not merged, and nothing was posted to the PR.
- **Patch:** `cutscenecity-phase1.patch` (git format-patch, 1 commit).
  - SHA-256 `c2947c863a5d50c5594a7e56a3773738848a2697e3891f52285994c3f44633fe`
  - 13 files, +1525 / −26
  - Applies cleanly to `8cbb605`.
- **Tests:** 18 out of 18 pass. That covers the 2 original QA tests and 16 new ones. The new tests include end-to-end review → export → PRIVATE upload runs against a **mocked** YouTube client. No real account was touched.
- **Handover document:** I couldn't find "CutsceneCity — COMPLETE AI CLIPPING & YOUTUBE AUTOMATION PROJECT HANDOVER". It isn't in the agent attachments folder, the PR body, the repo, or Google Drive (search "CutsceneCity handover" returned 0 results). I audited against `EDITORIAL_PROMPTS.md` and `editorial-policy.json` in the PR, and against the named requirements: semantic understanding, Mode A/B, scoring, multi-agent.

## 1. Audit of PR #1 (original code)

### Good
- All subprocess calls use argument lists, with no `shell=True`.
- The VOD URL must pass the full-match check `https://(www.)twitch.tv/videos/<digits>`.
- The workflow passes `inputs` through `env:`. It doesn't interpolate them into `run:`, so there is no script injection.
- The workflow runs with `permissions: contents: read`.
- The workflow is manual-only (`workflow_dispatch`), and it doesn't upload to YouTube.
- QA fails closed on missing or empty files, decodes the full file, and sets `publish_allowed: false` everywhere.
- No secrets are in the repo. A scan for `AIza`, `sk-`, `ya29.` and client_secret found nothing.

### Problems
| # | Severity | Finding |
|---|---|---|
| A1 | High (rights) | The workflow uploads the rendered clips as GitHub artifacts (3-day retention). On a public fork, any signed-in GitHub user can download them. For third-party streams (Speed, Kai Cenat), that is redistribution before any rights review. |
| A2 | High (policy) | `editorial-policy.json` (rubric, thresholds, `required_gates`, dedup) is **not read by any code**. None of the gates are enforced. They exist only as prompts and documentation. |
| A3 | High (rights) | The PR's prompts say "creator-owned VODs only", but the parent request (t11u) is to clip IShowSpeed, Kai Cenat and others. Those two conflict. The PR also hard-coded a default VOD whose ownership was unverified. Phase 2 removed it. |
| A4 | Medium | Selection is based on motion only: the 75th percentile of frame differences every 2 s, in fixed 35 s windows. It has no audio, chat or transcript signal, and it gives no reason for its picks. |
| A5 | Medium | The only layout is letterbox `pad`, which leaves black bars on 9:16. There is no loudness normalisation and no captions. |
| A6 | Medium | Re-running into the same `--output` silently reuses a stale `vod.*` from an earlier VOD. |
| A7 | Medium | Long VODs (Speed streams run 6–10 h) will exceed GitHub-hosted runner disk and the 110-minute timeout. CV seeking every 2 s with `CAP_PROP_POS_MSEC` is slow and imprecise on Twitch VFR files. |
| A8 | Low | `visual_review.py` sends 4 frames per clip to Gemini when the secret is set. It is fine as advisory only, but the frames leave the machine. Its suffix match is case-sensitive. |
| A9 | Low | Actions are pinned by tag (`@v4`, `@v5`), not by SHA. |
| A10 | Low | There are only 2 tests, and nothing tests selection or rendering. The branch has 11 commits with duplicated messages; squash before any merge. |
| A11 | Low | The README calls vidIQ the "connected" destination. vidIQ is an analytics/SEO tool, not an uploader, so uploading still needs its own OAuth path. |

## 2. Gaps against the handover requirements (handover doc not found)
| Requirement | PR #1 | After phase 1 |
|---|---|---|
| Semantic understanding (what happens in the clip) | None. Motion only, plus optional Gemini assessment of 4 stills | Still none. Adds audio peaks, chat velocity and transcript keywords as **signals**, but no scene understanding |
| Mode A / Mode B | Not defined anywhere I could find | Not implemented. I need the handover's definition |
| 100-point editorial rubric | Text in the prompts and policy only | Not computed. `combined_score` is a signal ranking, not the rubric, and a human still judges hook and payoff |
| Multi-agent stages (ingest → scene map → selector → editor → QA → packaging → rights → approval) | Prompts only, no orchestration | Review CLI covers rights → approval → packaging. `ingest.json`, `scene_inventory.json` and `edit_decision_list.json` are still missing |
| Dedup ledger by VOD + range + fingerprint | Policy text only | Ledger by file SHA, package SHA and overlapping VOD range. No perceptual fingerprint |
| Metadata generation (3 titles etc.) | Prompt only | Manual (`clip-details.json`). Spoiler and attribution checks run on it |
| Facecam detection | None | Facecam box set by hand (`--facecam-box`). No auto-detect |
| Analytics loop (24 h / 7 d) | Policy only | None |
| Node agent integration | None | Package handoff (`agent-import.json`) only. No route in the agent yet (see §5) |

## 3. Compliance gates: PR #1 vs this branch
In the table, "minimal" means present but weak.

| # | Gate | PR #1 (original) | `cutscenecity-phase1-tweaks` |
|---|---|---|---|
| 1 | Provenance and licence record per clip; rejected if missing or expired; own channel whitelisted | **Missing** (text only) | **Present (creator-owned only, Phase 2.1).** `creator_owned_source` (auto) reads `yt-dlp -J` metadata **before download**. It requires the URL's VOD id to match the metadata, and `uploader_id`/`channel` (or `channel_id`) to match `CUTSCENECITY_OWNER_TWITCH_LOGIN` / `CUTSCENECITY_OWNER_TWITCH_ID` (env placeholders, unset by default). It fails closed when the owner is unset, the channel is unknown, or only a display name is present. The third-party licence path was removed. Human `vod_rights_confirmed` is still required. |
| 2 | Cutscene detection that blocks until human sign-off | **Missing** (prompt text) | **Minimal.** A letterbox-bar heuristic (`review.py precheck`) gives a hint. `no_story_cutscene` always blocks until a named human signs off, and a warning needs a written note. The heuristic is weak: it misses cutscenes without bars. |
| 3 | Strip music/radio plus fingerprint pre-check | **Missing** | **Minimal.** (Phase 2.8 override: game audio is KEPT by default, `mix` = game + mic at 1.0 + optional voiceover; `--strip-game-audio` gives `mic_stem`, the creator mic only.) The mic must be a separate track (OBS multitrack or a mic file). A Twitch VOD's single mixed track can't be separated, so the tool fails closed (no stem separation is built). The `fingerprint()` hook runs Chromaprint `fpcalc` but does **no matching**. `music_risk_cleared` needs a fingerprint pre-check and a human sign-off. YouTube's Content ID check on the private upload is the real test. |
| 4 | Original commentary track covering at least 60% of runtime | **Missing** | **Present (v3).** VAD (ffmpeg `silencedetect`) runs on the commentary bus: the live mic plus the TTS voiceover. TTS counts by default (`CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY=true`), and any TTS forces `containsSyntheticMedia=true`. With TTS, a human-edited script is required and approved in the signed log. The script is checked for reuse against the last 30 (Jaccard on 3-word shingles: a note is needed at 40% or more, above 50% is rejected, and a reused opener or CTA is rejected). Voice preset and caption style rotate, so neither may repeat the previous upload's. The live reaction is never muted or ducked (`live_reaction_preserved`). |
| 5 | Signed human review log | **Missing** | **Present.** `review_log.jsonl` is an HMAC-SHA256 hash chain keyed by `CUTSCENECITY_REVIEW_KEY` (env only). Sign-offs and approval are bound to the file SHA-256 and the metadata hash. Editing the log or the file invalidates it, and re-rendering revokes the sign-offs. One shared local key: it proves "someone with the key", not a specific person. |
| 6 | Forced private, MFK false, synthetic flag when TTS used, no public or scheduled uploads from code | **N/A / missing.** There is no upload code, so nothing publishes, but nothing enforces it either | **Present** (mock-tested). `upload_private.build_body` hard-codes `privacyStatus=private` and `selfDeclaredMadeForKids=false`, and never sends `publishAt`. `containsSyntheticMedia` is always sent and is forced true when TTS or AI visuals are used. The returned privacy is checked (it raises if it isn't private). Only the `youtube.upload` scope is requested. |
| 7 | Daily cap and duplicate check | **Missing** (policy text) | **Present.** The ledger blocks at the effective cap per IST day: `min(CUTSCENECITY_DAILY_CAP or policy, 1)`. It's hard-capped at 1 in Python and Node, and 0, negative or invalid values block everything (Phase 2.2). **Phase 2.5 raised the hard cap to 2** (§13). It blocks a repeat file or package and any overlap with an already-sent range of the same VOD. A timeout mid-upload is blocked until a human runs `reconcile`. |
| 8 | Spoiler keyword block in metadata | **Missing** (prompt) | **Present.** `metadata_spoiler_free` does a whole-word match of title, description and tags against built-in terms plus `spoiler-keywords.txt`. |
| 9 | Per-upload audit log | **Missing** | **Present.** `~/.cutscenecity/upload-audit.jsonl` records ATTEMPT before the call and UPLOADED, UNKNOWN_RECONCILE or FAILED after it, with the SHAs, the approver and the video ID. |

The branch also adds:
- `attribution`: the description must name the streamer and link the VOD URL.
- `transformation_note`: at least 25 words on what the Short adds.
- `technical_qa`: qa.py must pass on the final render.

## 4. Compliance-hook stage (pluggable, default deny)
`compliance.py` keeps a registry. Every check starts at `PENDING`, and anything that isn't `PASS` blocks approve, export and upload.

There are two kinds of check:
- **auto** checks are computed from the manifest and media. Only code sets PASS or FAIL, and a human can't override an auto FAIL.
- **human** checks reach PASS only through `review.py signoff --by NAME`. An optional hint runs first:
  - a hint FAIL blocks the sign-off;
  - a hint WARN needs a note of at least 5 words;
  - if a hint later turns FAIL, the sign-off is revoked.

The built-in checks are: `provenance_licence`, `vod_rights_confirmed`, `no_story_cutscene`, `music_risk_cleared`, `original_commentary`, `attribution`, `transformation_note`, `metadata_spoiler_free`, `synthetic_disclosure`, `technical_qa`.

There are two ways for a compliance reviewer to register a new check.

The first needs no code. Add the check to `tools/twitch-shorts/editorial-policy.json`, and it becomes a blocking human check on every clip:
```json
"extra_human_checks": [{"name": "content_id_cleared", "description": "Studio copyright check shows no claims"}]
```

The second uses code, for an automatic check or a human check with a hint:
```python
from compliance import register_check, PASS, FAIL, WARN
@register_check("no_licensed_radio", kind="human", description="No in-game radio station audible")
def radio_hint(clip, ctx):
    return (PASS, "source audio muted") if clip.get("render", {}).get("audio_mode") == "mute" else (WARN, "listen for radio")
```
Upload re-runs every check from the package's `clip.json`. It also requires a signed sign-off in the log for every human check against the exact approved file, so editing `manifest.json` by hand gets nowhere.

## 5. What changed (files under `tools/twitch-shorts/`)
- **`signals.py`**: motion, audio loudness (per-second RMS), optional chat velocity (TwitchDownloader JSON) and transcript keywords. Signals are compared by percentile rank, and missing ones are dropped. Each candidate gets a `selection_note` saying why it was chosen, with scores and timestamps. Picks run from 0 to the limit, not to a quota.
- **`render.py`**:
  - Layouts: `pad`, `blur` (blurred fill), `crop` (fixed or `smart` motion-centroid) and `split` (facecam top / gameplay bottom, with `--facecam-box x,y,w,h`).
  - `--captions` uses faster-whisper when installed and skips gracefully otherwise. Captions burn in through a plain relative filename, with no path escaping.
  - Every render gets `loudnorm` to −14 LUFS (verified −14.0 LUFS integrated).
- **`pipeline.py`**: uses the above, writes a v2 manifest with provenance and metadata placeholders and default-deny compliance, and refuses a stale VOD. Running with no new flags gives the same behaviour as PR #1 (pad layout).
- **`compliance.py`, `gatelog.py`, `review.py`, `upload_private.py`**: the gates, the signed log, the review CLI, and a gated private uploader. The uploader is a dry run by default. Executing needs `--execute --confirm <first 12 of package SHA>`.
- **`editorial-policy.json` v2**: adds `min_commentary_coverage` 0.6, `allow_tts_commentary` false, `daily_upload_cap` 2, the spoiler file and `extra_human_checks`.
- **`requirements-local.txt`**: Google client libraries and faster-whisper, for the Mac only. CI never installs them.
- **`.gitignore`**: covers output, packages, tokens, client secrets and the review log.
- **Workflow is unchanged.** A test asserts that it never references the uploader, YouTube secrets or the review key.

**Human-like AI rules:** AI is optional here. TTS commentary is off by default, and if it is used, `containsSyntheticMedia` is forced true. Gemini frame review stays advisory. Captions are only ever a transcription of what was said, never generated text.

**Combining with the existing agent:** the PR branch is based on `master` and has none of `gta6-originality`, `gta6-human-style` or `gta6-ai-generation`. I didn't force a merge. The gta6 approval flow is built for long-form productions (450-word script gate, fact-check), and a VOD clip can't pass it as it stands. Phase 1 therefore uses a standalone Python uploader that follows the same rules: force-private, per-upload approval and the synthetic flag. Each export also writes `agent-import.json`, whose field names match the gta6 Shorts rows. A later step on the gta6 line would be a `POST /api/gta6/external-shorts` route that verifies the package SHA and the signed log, then calls the existing `publishing-scheduling-agent` upload, which already forces private. That route isn't built.

## 6. Mac step-by-step: one PRIVATE test upload
All credentials stay in `~/.cutscenecity/`, outside the repo. Never paste them into chat.

1. **Get the code.** Either `git fetch origin cutscenecity-phase1-tweaks && git switch cutscenecity-phase1-tweaks` once it's pushed, or apply the patch:
   ```bash
   cd ~/youtube-automation-agent && git fetch origin
   git switch -c cutscenecity-phase1-tweaks origin/feature/cutscenecity-twitch-vod-shorts
   git am ~/Downloads/cutscenecity-phase2.2.patch      # cumulative from 8cbb605; check its SHA-256 (§10)
   ```
2. **Install tools:**
   ```bash
   brew install python@3.11 ffmpeg yt-dlp chromaprint
   cd tools/twitch-shorts && python3.11 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt -r requirements-local.txt
   python -m unittest discover -s . -p "test_*.py"   # expect OK (46 tests)
   ```
3. **Set up the Google OAuth Desktop client** (once):
   1. In console.cloud.google.com, create a project and enable **YouTube Data API v3**.
   2. On the OAuth consent screen, choose External, keep it in Testing, and add the CutsceneCity Google account as a **test user**.
   3. Under Credentials, create an OAuth client ID with type **Desktop app**. Download the JSON to `~/.cutscenecity/client_secret.json`, then `chmod 600` it.
   - In Testing mode, refresh tokens expire after 7 days, so you'll need to sign in again after that.
4. **Create `~/.cutscenecity/env`** (placeholders shown):
   ```bash
   export CUTSCENECITY_CLIENT_SECRETS="$HOME/.cutscenecity/client_secret.json"
   export CUTSCENECITY_OWNER_TWITCH_LOGIN="<your-twitch-login>"    # gate 1: unset = everything blocked
   # export CUTSCENECITY_OWNER_TWITCH_ID="<numeric id>"            # optional; Twitch VOD metadata rarely has it, so set the LOGIN
   export CUTSCENECITY_REVIEW_KEY="<output of: openssl rand -hex 32>"
   export CUTSCENECITY_DAILY_CAP=2                                    # policy default is 2 (Phase 2.5); hard max 2
   export CUTSCENECITY_STATE_DIR="$HOME/.cutscenecity"
   ```
   Then run `chmod 600 ~/.cutscenecity/env && source ~/.cutscenecity/env`.
5. **Record with OBS multitrack** (required for the live-reaction gate). In OBS go to Settings → Output → Recording, tick Audio Tracks 1 and 2, and route the mic to track 2 only (Edit → Advanced Audio Properties). Track 1 is the full mix. In the review step that file's mic is `--mic-stream 1` (0-based audio index). A downloaded Twitch VOD has only the mixed track. Use the local recording as `--input` together with the VOD's metadata.
6. **Find candidates** from one of **your own** VODs. The owner check runs before anything is downloaded:
   ```bash
   yt-dlp -J https://www.twitch.tv/videos/<id> > vod.info.json        # metadata only
   python pipeline.py --input ~/Movies/<obs-recording>.mkv --info-json vod.info.json \
     --output output --limit 4 --render --profile facecam-right-chat-left
   ```
   Or use `--url https://www.twitch.tv/videos/<id>` (mixed audio only, so you'll still need `--mic` later). Edit the profile boxes in `editorial-policy.json` to match your scene. Watch `output/short_0*.mp4` and read each `selection_note`.
7. **Prepare commentary and details.** Optionally write a TTS voiceover script (20+ words, your own wording) and render it with a voice preset from the policy. Fill in `clip-details.json`. Provenance comes from yt-dlp and can't be set by hand:
   ```json
   {"metadata": {"title": "<what actually happens>", "description": "<your line>. Clip from <Your Twitch name>: https://www.twitch.tv/videos/<id>",
     "tags": ["gta"], "privacyStatus": "private", "containsSyntheticMedia": false},
    "transformation_note": "<25+ words: what your commentary and edit add beyond the raw stream>"}
   ```
8. **Review and approve.** Each command stops and tells you what is still blocking.
   ```bash
   C=short_01.mp4
   python review.py set --clip $C --file clip-details.json --by "Shebin"
   python review.py commentary --clip $C --mic-stream 1                       # live mic only, or:
   python review.py commentary --clip $C --mic-stream 1 --audio vo.wav --tts --voice-preset puck-hyped --caption-style yellow-pop --captions
   python review.py script --clip $C --file script.txt --by "Shebin"          # required with --tts
   python review.py precheck --clip $C        # cutscene + fingerprint + overlay scan of the FINAL render (re-run after any re-render)
   python review.py status --clip $C
   python review.py signoff --clip $C --check vod_rights_confirmed --by "Shebin" --note "my own stream, my capture"
   python review.py signoff --clip $C --check no_story_cutscene --by "Shebin" --note "watched all of it, free-roam gameplay only"
   python review.py signoff --clip $C --check music_risk_cleared --by "Shebin" --note "game audio dropped, only my mic and voiceover"
   python review.py signoff --clip $C --check overlays_third_parties_cleared --by "Shebin" --note "chat and alerts blurred, no viewer TTS, no guests"
   python review.py paid --clip $C --value none --by "Shebin"     # or --value present if there's any sponsor overlay, read or placement
   python review.py approve --clip $C --by "Shebin"     # watch the FINAL file before this
   python review.py export --clip $C
   ```
9. **Upload as PRIVATE:**
   ```bash
   python upload_private.py check  --package packages/short_01-<sha12>
   python upload_private.py upload --package packages/short_01-<sha12>              # dry run: shows the exact request
   python upload_private.py upload --package packages/short_01-<sha12> --execute --confirm <sha12>
   ```
   On the first run a browser opens at `127.0.0.1` for Google sign-in. Choose the CutsceneCity account.
10. **Check that it's private in Studio:**
    1. In studio.youtube.com → Content, the Visibility column should say **Private**.
    2. On the video's Details page, Audience should be "No, it's not made for kids". The Altered content answer should match the package.
    3. The Checks (copyright) column is the real music/Content ID result; wait for it to finish.
    4. Open the watch URL in a private browser window. It should say the video is private.
    5. `tail ~/.cutscenecity/upload-audit.jsonl` should show ATTEMPT then UPLOADED with the video ID.
    6. If the upload errors halfway, check Studio first, then run `python upload_private.py reconcile --package ... --video-id <id or NONE> --by "Shebin"`.

**Note (corrected in Phase 2):** YouTube reversed the private-only rule for unaudited API projects on 2 Nov 2026. Uploads with no `privacyStatus` now default to **public**, so the explicit `private` in the code is essential. See `youtube-api-audit/README.md`.

## 7. What blocks a working review-then-private-upload path today
1. **The branch exists only on the box.** It isn't on GitHub or your Mac. You need to approve pushing it, or say how the patch file should reach you.
2. **There's no OAuth Desktop client or test user yet.** You have to create them in Google Cloud yourself (step 3).
3. **Rights.** Gate 1 passes only for your own whitelisted channel (Phase 2: own VODs only, third-party licences off).
4. **Your own commentary is needed per clip** (60% rule). TTS doesn't count unless you set `allow_tts_commentary: true`.
5. **The real upload code path is unexecuted.** That is `get_service` and `MediaFileUpload`: only the mocked path has been tested. The first real run is the test.
6. ~~Unaudited API project means uploads stay private-locked.~~ This is no longer true: YouTube reversed that rule on 2 Nov 2026 (see Phase 2).
7. **Twitch availability.** VODs expire (7–60 days) and sub-only or deleted VODs fail to download. Long VODs are too big for GitHub runners, so run them locally.
8. **Optional tools are missing:** faster-whisper (captions) and fpcalc (fingerprint). The path works without them, but music needs `mute` or a careful human listen.
9. **The handover doc wasn't found,** so Mode A/B and the exact scoring are undefined.

## 8. Phase 2 (Shebin's decisions applied)
- **Branch:** `cutscenecity-phase1-tweaks`, commits `ccad4e8` (phase 1) and `2099db3` (phase 2).
- **Cumulative patch:** `cutscenecity-phase2.patch`, compared with the PR head `8cbb605`.
  - 2 commits; apply with `git am`.
  - SHA-256 `a511cf506695beac382d23438fd7f0e734c4a44688dd8a43100b96cf78b0a500`.
  - 21 files, +2343 / −35.
  - Verified: applying it to `8cbb605` reproduces the branch tree exactly.
- **Tests:**
  - Python: 22 out of 22.
  - Node route: 12 out of 12 (`node --test tests/cutscenecity-external-shorts.test.js`, with YouTube mocked).
  - Existing system test (`node test.js`): 49 out of 49.
  - `npm run test:cutscenecity` runs the Python and Node-route suites together.

### Decisions applied
| # | Decision | What changed |
|---|---|---|
| 1 | Keep on the box, cumulative patch | See above |
| 2 | Own VODs only | Removed the default VOD from the workflow input, `pipeline.py`, policy, README and tests (a test checks it's gone). `--url` (or `--input`) is now required. The policy has `source_policy: own_vods_only` and `third_party_licences_enabled: false`. Gate 1 rejected channels outside a whitelist; **superseded in Phase 2.1** by the creator-owned owner match, and the licence path was removed (see §9). |
| 3 | TTS **can** count toward the 60% rule (reversed) | It counts only when `containsSyntheticMedia` is true. Without that, both `original_commentary` and `synthetic_disclosure` fail. `review.py commentary --tts` sets the flag automatically. Covered by tests in Python and Node. |
| 4 | CI artifact step unchanged (reversed) | The workflow is identical to the PR except the `vod_url` input, which has no default and a new description. Rendered clips are still uploaded as 3-day artifacts. Finding A1 (public-fork exposure) still applies; with own VODs only, the risk is lower. |
| 5 | Daily cap = 1 (now 2, see §13) | `editorial-policy.json` `daily_upload_cap: 1`, used by both the Python and Node paths. `CUTSCENECITY_DAILY_CAP` can still override it locally. |
| 6 | Default layout = blur | `pipeline.py --layout` defaults to `blur`, and re-renders with commentary default to `blur`. |
| 7 | Node ingest route | See below |
| 8 | API audit later | Audit package in `youtube-api-audit/`. It's probably **not needed**: YouTube reversed the private-only rule for unaudited projects on 2 Nov 2026 (official revision history), and cap 2/day (Phase 2.5) is far below the default quota. |

Python also gained `upload_private.py revoke`, which revokes the OAuth token at Google and deletes it locally, as the Developer Policies require. Spoiler defaults now live in `spoiler-defaults.json`, which Python and Node share.

### Node route: `POST /api/gta6/external-shorts`
The code is in `utils/cutscenecity/external-shorts.js` and is wired into `index.js` on this branch, which is based on master.

1. **Auth:** the route needs `x-api-key` to equal `API_KEY`, compared in constant time.
   - If `API_KEY` is unset, it fails closed with 503. That is stricter than master's legacy routes, which stay open without a key.
2. **Ingest:**
   1. It validates the `agent-import.json` schema and rejects unknown fields, any `publishAt` (at any depth), anything not private, and `selfDeclaredMadeForKids` other than false.
   2. The `videoPath` must resolve inside `CUTSCENECITY_PACKAGES_DIR`, with no path escape.
   3. It recomputes the package SHA. Node's canonical JSON is byte-identical to Python's `json.dumps(sort_keys)`, and a test proves it. It also recomputes the video SHA.
   4. It verifies the HMAC review-log chain with `CUTSCENECITY_REVIEW_KEY` and checks that the signed approval matches the exact file and metadata. Every human check must have a signed sign-off for this file.
   5. It then **re-checks every gate itself**: own-channel whitelist, attribution, spoiler words, the 60% commentary rule (TTS allowed only with the AI flag), the synthetic flag, transformation note, technical QA, and all compliance entries PASS.
   6. Finally it checks the daily cap and duplicates against both the shared ledger (`CUTSCENECITY_STATE_DIR/upload-audit.jsonl`, the same file the Python uploader uses) and items already ingested.
   7. The item is then stored as `pending_approval` with `autoUpload: false`. Ingest never uploads.
3. **Approval click:** `POST /api/gta6/external-shorts/:id/approve-upload` with `{reviewer, confirm: <first 12 of packageSha256>}`. The CLI version is `npm run cutscenecity:shorts -- approve <id>`.
   1. It re-runs the full verification.
   2. It writes an ATTEMPT line to the audit log, then makes one `videos.insert` call with `privacyStatus: private`, `selfDeclaredMadeForKids: false` and `containsSyntheticMedia` (forced true when TTS was used). There is no `publishAt`.
   3. It writes UPLOADED with the video ID.
   4. An upload error is recorded as UNKNOWN_RECONCILE, and nothing retries it automatically. If YouTube returns a status other than private, the item is flagged and you're told to fix it in Studio.
4. `GET /api/gta6/external-shorts` lists the items.
5. The route uses master's existing `PublishingSchedulingAgent` YouTube client (the agent's own OAuth). No new credentials go into the agent.

**Porting to the gta6 line** (`gta6-originality` → `gta6-ai-generation`):
- Move `registerExternalShortsRoutes` into `utils/gta6/routes.js`, and use `gate-store.js` for the pending items instead of the JSON store.
- Make the approval click call the gta6 publishing agent's private-forced `uploadToYouTube` path. It already forces private and the synthetic flag, so the explicit status block stays as a second guard.
- Add the item to the dashboard's existing final-gate confirm dialog.
- The verification module carries over unchanged.
- Not done: the gta6 branches are unpushed and separate from this PR's base.

### Mac: test the Node path (after the Python export in §6 step 8)
```bash
# .env (placeholders only): API_KEY=<long random>, CUTSCENECITY_PACKAGES_DIR=/Users/<you>/.../tools/twitch-shorts/packages
# plus the same CUTSCENECITY_REVIEW_KEY / OWNER_TWITCH_LOGIN / STATE_DIR as ~/.cutscenecity/env
npm start                                     # dashboard on 127.0.0.1:3456; finish its YouTube OAuth setup first
npm run cutscenecity:shorts -- ingest tools/twitch-shorts/packages/short_01-<sha12>/agent-import.json
npm run cutscenecity:shorts -- list
npm run cutscenecity:shorts -- approve <itemId>   # type your name + confirm code: the per-upload approval click
```
Then check it's private in Studio, as in §6 step 10. Use **either** the Python uploader **or** the Node route for a given package. They share the ledger, so the second one is blocked as a duplicate.

### Still blocked or not done
1. **Real upload never executed:** both upload paths were tested only with mocks.
2. **Your setup on the Mac:**
   - create the OAuth Desktop client and test user;
   - finish the agent's YouTube OAuth;
   - set `.env` placeholders;
   - record your own commentary, or TTS with the AI disclosure, for each clip.
3. **Paid-promotion field:** resolved in Phase 2.2 (§10). Both upload paths now always send `hasPaidProductPlacement` explicitly, based on the signed reviewer declaration.
4. **Still not built:**
   - semantic understanding, Mode A/B and the rubric (the handover document is still missing);
   - facecam auto-detection;
   - perceptual duplicate checks;
   - a dashboard UI for the pending items (CLI and API only).
5. **API audit:** optional; see `youtube-api-audit/README.md`.

## 9. Phase 2.1: creator-owned gate 1 and gate 4 v3 (commit `6050263`)
**Gate 1 (`creator_owned_source`)**
- `pipeline.py` runs `yt-dlp -J --no-playlist` and checks the owner **before any download**, refusing with no download. `--input` needs `--info-json`. The owner record (vod_id, uploader, uploader_id, channel, channel_id) is stored in `provenance.source_owner`, can't be set with `review.py set`, and is hash-bound in the approval.
- It passes only if `uploader_id` or `channel` equals `CUTSCENECITY_OWNER_TWITCH_LOGIN` (case-insensitive), or `channel_id` equals `CUTSCENECITY_OWNER_TWITCH_ID`.
- It fails closed when:
  - the owner isn't set;
  - there's no channel field;
  - any field contradicts the owner;
  - only the display name is present.
- Twitch VOD metadata has `uploader_id` (the login) but usually no numeric `channel_id`, so set the LOGIN. The licence path and its policy flags are deleted.

**Gate 4 v3**
- (a) With TTS, `review.py script` is required. It stores the script and signs `script_approve` (script SHA) in the HMAC log. Approve, export, the uploader and the Node route all re-check that hash.
- (b) The script is compared with the last 30 scripts (`script-history.jsonl`, recorded at approve) using 3-word-shingle Jaccard:
  - 40% or more needs a 5-word reviewer note;
  - above 50% is rejected;
  - a reused first or last sentence (exact, or word-set Jaccard of 0.8 or more) is rejected.

  Python and Node are parity-tested.
- (c) `voice_presets` (charon-relaxed/puck-hyped/kore-dry) and `caption_styles` (bold-white/yellow-pop/clean-lower) live in the policy. Neither may repeat the previous ATTEMPT/UPLOADED ledger entry. The ledger records both.
- (d) VAD runs on the commentary bus, which is the mic plus the TTS voiceover. The 60% check uses combined speech when `CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY=true` (default), otherwise live speech only.
  - The render's only audio mode is `mic_stem`: the mic at gain 1.0 (`amix normalize=0`, then loudnorm -14 LUFS), with game and music dropped. `mute` and `duck` were removed.
  - **Facecam mic separation:** a downloaded Twitch VOD has one mixed track, so separation isn't possible from it. Record OBS multitrack (mic on its own track, `--mic-stream N`) or supply a mic file on the VOD timeline (`--mic`). Otherwise `commentary` refuses and `live_reaction_preserved` fails.
- (e) Any TTS forces `containsSyntheticMedia=true` in the manifest, the package, Python `build_body` and the Node request body.

**Other changes**
- **Profiles:** `stream_layout_profiles` in the policy, each with `facecam_box` and `blur_regions` (fractions); select one with `--profile`. `default_layout_profile` is a placeholder with no blur. `facecam-right-chat-left` blurs the left chat column.
- **Unchanged from v2:** the 9 gates; the CI artifact step; cap 1; blur default; private-only, MFK false, no publishAt; the Node route contract (schema `/3` adds a `style` block).
- **CI side effect:** the review-only workflow doesn't export `CUTSCENECITY_OWNER_TWITCH_LOGIN`, so its candidate step now stops at the owner check (fail closed). Making CI work needs a one-line workflow `env:` from a repo variable. I didn't add it, because the workflow was to stay as in the PR.
- **Tests:** Python 38 OK, Node route 17/17, `node test.js` 49/49, eslint clean.
- **Patch:** `cutscenecity-phase2.1.patch` (cumulative 8cbb605..6050263, 3 commits, 22 files, +3183/−35, 4843 lines). SHA-256 `9e09a7f19680b7257cb079de38816c8850b3842cbf293fbb18412983ec2ad3d7`. `git am` on 8cbb605 reproduces the branch tree `29dcc3e`.
- **Push:** blocked, because the box has no GitHub credentials.

## 10. Phase 2.2: blocking fixes (commit `8915135`, local only, not pushed)
1. **Daily cap is hard-capped at 1** (superseded: 2 since Phase 2.5, §13).
   - `gatelog.effective_daily_cap` and Node `effectiveDailyCap` compute `min(CUTSCENECITY_DAILY_CAP or policy, 1)`.
   - 0, negative, non-integer and boolean values give 0, which means "uploads disabled".
   - `upload_blockers` also re-clamps whatever cap it's given, so a caller can't pass a higher one.
2. **`overlays_third_parties_cleared`** is a human check that's always required. It covers:
   - chat, alert and username regions blurred in the FINAL render;
   - no viewer TTS or donation audio;
   - no guest or voice-chat audio.

   It's in `REQUIRED_HUMAN_CHECKS` (Node) and the Python registry. Approve, export, the uploader and the Node route all need a signed sign-off bound to the file hash.
   - **Overlay text detection:** this wasn't implemented before (blur regions were config only). It's now added in `overlay_scan.py` and runs from `review.py precheck` on the final render.
     - Edge density: a cell that's both edge-dense (Canny) and static across 8 sampled frames gets flagged.
     - Tesseract OCR runs when it's installed: a frame with 3+ words at confidence 60+ counts, and 2+ such frames flag the clip. Only counts and boxes are stored, never text.
   - Tesseract is **not installed on the build box**, so its path is tested with a mocked CLI. The edge path is tested on synthetic video: a static chat-like box is flagged, while moving noise and a blurred frame aren't.
   - A flagged result, or no detector at all, makes the hint WARN, so the sign-off needs a note of 5+ words. A missing or stale scan blocks the sign-off.
   - Re-rendering clears the scan and the paid declaration. A persistent own HUD (minimap) will also be flagged, which only means writing a note.
3. **Paid promotion.** Run `review.py paid --value none|present --by NAME`.
   - The statement is signed and bound to the file hash: "none" means no sponsor overlay, read or product placement.
   - The value goes into the approval entry, the package (`paidProductPlacement`) and the agent import.
   - The upload always sends `paidProductPlacementDetails.hasPaidProductPlacement` (false or true) with part `snippet,status,paidProductPlacementDetails`. This field and part are verified against the live videos resource docs.
   - A missing or mismatched value blocks in every runtime.
- Package schema is now `/4`.
- **Tests:** Python 50 OK, Node route 20/20, `node test.js` 49/49, eslint clean.
- **Patch:** `cutscenecity-phase2.2.patch` (cumulative 8cbb605..8915135, 4 commits, 24 files, +3784/−35, 6188 lines). SHA-256 `de6f11b25e821032e16442c6b41480d990cf0e79540326f48ffbb89c06921028`. `git am` on 8cbb605 reproduces the branch tree `c004743`.
- **Owner default (same commit):** the policy has `owner_twitch_login: "cutscenecity"`, and `.env.example` has `CUTSCENECITY_OWNER_TWITCH_LOGIN=cutscenecity` (a public login, not a secret). Precedence is env first, then policy; if both are empty, every VOD is rejected. Tests show cutscenecity VODs pass and others (ishowspeed, cutscenecity_fan, xqc) are rejected. With the policy default, the CI candidate step no longer stops at the owner check.
- **Game audio kept by default (Shebin, 10:32):**
  - All original game audio (music, voices, story/cutscene scenes) stays unchanged by default. The commentary render uses `mix` mode: game bed at `--music-volume`/`CUTSCENECITY_MUSIC_VOLUME` (default 1.0 = unchanged; must be above 0 and at most 1), with the mic and voiceover at 1.0. The amix doesn't normalise, and loudnorm -14 LUFS is overall loudness only.
  - Stripping game audio is opt-in (`--strip-game-audio`). No step drops cutscene segments. `no_story_cutscene` stays a human sign-off.
  - Gates aren't loosened: `live_reaction_preserved` still needs the mic in the mix at 1.0. `music_risk_cleared` still needs the fingerprint pre-check plus a signed sign-off, now with a required note, because kept audio gives a WARN instead of the old FAIL for unstripped audio.
  - For OBS, route game/desktop audio to track 1 without the mic.
  - **Licensed in-game radio music may trigger Content ID claims, so review it before any upload.**

## 11. Phase 2.3: OBS setup, mixed-track path, automatic defaults

> Superseded: the mixed-track path below was turned off in phase 2.7 and removed entirely in phase 2.8. A separate creator mic stem is always required.
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
- **Commit:** `a9cc76e` (local only, not pushed; the remote head 94c44e4 equals 8915135).
- **Tests:** Python 59 OK, Node route 22/22, `node test.js` 49/49, eslint clean.
- **Patches:**
  - Cumulative `cutscenecity-phase2.3.patch` (8cbb605..a9cc76e, 5 commits, 24 files, +4152/−35, 6893 lines). SHA-256 `0323cfc0fa884444e267cd5a0ee93bb6581ac99f08534f4a023a1e47b55949a9`. `git am` on 8cbb605 reproduces the branch tree `b75f95d`.
  - Incremental `cutscenecity-phase2.3-incremental.patch` (8915135..a9cc76e). SHA-256 `9ef6fa5dc7887ea5394e82a36906d1d590be7696b35a89cd91c3e00661255c0f`.
- **Review-only re-run:** `/workspace/clippers/review-out-2` (VOD <VOD_ID>, first 8 min, 3 clips). Each clip has precheck/status JSON next to its manifest.

## 12. Phase 2.4: upscale step (default 2160x3840)

- Every `--render` upscales the captioned 1080x1920 output to **2160x3840 by default**. Choose `--upscale 1440|2160|off` (flag), or set `CUTSCENECITY_UPSCALE` (the flag wins over the env var). Use `off` only for tests and debugging; the test suite sets `CUTSCENECITY_UPSCALE=off` so it stays fast.
- Order: ffmpeg render + captions → **upscale** → `qa.py` → overlay scan / `review.py precheck` → export SHA-256. QA, the overlay scan, precheck and the package hash all cover the final upscaled file.
- Method: ffmpeg `scale=W:H:flags=lanczos,unsharp=5:5:0.5:5:5:0.0`, libx264 preset medium, CRF 18, yuv420p, `+faststart`. The audio stream is copied unchanged (`-c:a copy`). The file is replaced in place through a temp file.
- It never upscales past the target. If the source is already at or above the target, the step is skipped and `render.upscale` records `skipped (...)`.
- **Honest note:** upscaling a 1080p source adds **no real detail**. The only benefit is that YouTube serves a 2160p upload with its higher-bitrate encode (VP9/AV1 4K ladder), which usually looks cleaner on phones than the 1080p encode.
- Measured on a 35 s 1080x1920 clip (8 vCPU box): about **+54 s** render time, and the file grew from **17.6 MB to 67.1 MB** (~3.8x, ~15 Mb/s). Audio MD5 was unchanged and qa passed.
- The Node route (`POST /api/gta6/external-shorts`) and `upload_private.py` accept 1080x1920, 1440x2560 and 2160x3840. The Node route rejects any other `render.upscale` value or output resolution.
- Re-render with the commentary stem: `review.py commentary ... --upscale 2160` (default) or `--upscale off`.

Commit `2b84976fa4a19a854e4a3e49574e9bd957c34d4e` (local only, not pushed). Patch `fork-patch/cutscenecity-phase2.4.patch` SHA-256 2008f816cb0ce53fed3d6cf99e39b584d13a780047ba987419c7a32fc04c8805 (6 commits from 8cbb605, 25 files, +4283/-36; git am tree a4f56c9 verified). Incremental: cutscenecity-phase2.4-incremental.patch SHA-256 362eb51b07ee5e459cf1faba516783be7a46c53c3b3c99a69e21998e6443491a.

## 13. Phase 2.5: daily cap raised from 1 to 2 (Shebin's approval)

- Hard clamp is now `min(cap, 2)`: `gatelog.HARD_DAILY_CAP = 2` and Node `HARD_DAILY_CAP = 2`. The `editorial-policy.json` `daily_upload_cap` and the `.env.example` default are both 2.
- Unchanged:
  - 0, negative, non-integer, boolean or unreadable values give 0, which blocks all uploads (fail closed). Values above 2 clamp to 2.
  - Day boundary: the **IST calendar day (Asia/Kolkata, UTC+05:30, midnight to midnight)**. Ledger timestamps are written in +05:30 by both Python and Node, and attempts are counted by that date.
  - Each upload is still private-only and needs its own human approval (package-SHA confirm code). `upload_private.py` and the Node route both re-check the cap and duplicates against the shared ledger.
- Tests: cap 5 gives 2, cap 2 gives 2, the 3rd upload on the same IST day is blocked (`2/2`), and the next IST day frees it up (Python and Node).
- Commit `2d33081204a6a92b28dc0c784ec1137fa1332ec3` (local only, not pushed). Tests: Python 63 OK, Node route 23/23, `node test.js` 49/49, eslint clean.
- Patch `fork-patch/cutscenecity-phase2.5.patch` (cumulative 8cbb605..2d33081, 7 commits, 25 files, +4318/-36, 7494 lines) SHA-256 `147f041170f4267fa840e30a63bb584ceda2ac1e73a52fcad4efa31aee075572`; `git am` on 8cbb605 gives tree `535f90a`. Incremental (2b84976..2d33081): `cutscenecity-phase2.5-incremental.patch` SHA-256 `e2e383ff3ce42daa7bdd4ab241489e637451bfbdf92e5658acf7032e035058e8`.

## 14. Phase 2.6: automatic edit stage (captions, animations, effects)

- `--edit-style off|clean|hype` on `pipeline.py --render` and `review.py commentary`, or env `CUTSCENECITY_EDIT_STYLE`. **Default `hype`.** `clean` = word-by-word captions only. `off` = no edit pass (the old `--captions` SRT path still works); the test suite sets `CUTSCENECITY_EDIT_STYLE=off` to stay fast.
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
- Commit `02c223ca703914ae6ff78bcfb370be59b0bb5f1d` (local only, not pushed). Tests: Python 68 OK, Node route 23/23, `node test.js` 49/49, eslint clean.
- Patch `fork-patch/cutscenecity-phase2.6.patch` (cumulative 8cbb605..02c223c, 8 commits, 26 files, +4768/-36) SHA-256 `6bdbea664601de7add76f9ef0d8fe323d7da312aa39cb78572cc41fb4ab2fd52`; `git am` tree `a034cd2`. Incremental: `cutscenecity-phase2.6-incremental.patch` SHA-256 `fc359f06c53a57a7b8997bcdd9efedd2678ce803b4d5d9c354e4a3d3cfe19613`.
