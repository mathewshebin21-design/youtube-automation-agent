# CutsceneCity clippers evaluation

Checked 23 Nov 2026, Asia/Calcutta (IST). No GitHub pushes, PR comments, or changes to the fork worktree. Clipper clones are under `/workspace/clippers/` only. Another worker was actively editing `/workspace/gta6-automation/fork` on `cutscenecity-phase1-tweaks`; that directory was inspected with read-only `git` only.

Stats below are from `git ls-remote`, the public GitHub API, local `git log`, and each repo’s README/code. Anything not directly confirmed is marked **UNVERIFIED**.

---

## 1. Repo state: `mathewshebin21-design/youtube-automation-agent`

Public fork of `darkzOGx/youtube-automation-agent`. License MIT. Visibility: **public**. Default branch: **`master`** at `e973d515aef90c467da2289144df737a3bd03859` (`docs: lead the README with dashboard screenshots…`, #86).

### Remote branches (`git ls-remote` / API, 23 Nov 2026)

| Branch | Head | Notes |
|---|---|---|
| `master` | `e973d51` | Default |
| `feature/cutscenecity-twitch-vod-shorts` | `8cbb605cad474f095ecd62bbd0bb682611d71d3c` | Head of draft PR #1 |
| `gta6-improvements` | `548c4a55edf8374d4cc6b8874a8ee6776b769acf` | On the fork. **Do not merge** (see below) |

Tags exist from `v2.2.0` through `v2.11.0`. Last remote push: `2026-11-22T04:50:51Z` = **22 Nov 2026, 10:20 AM IST**.

### Open PRs

One PR, still a draft, not merged:

- **[PR #1](https://github.com/mathewshebin21-design/youtube-automation-agent/pull/1)** — “Add review-gated Twitch VOD → Shorts pipeline for CutsceneCity”
- State: open, **draft: true**, mergeable/clean at check time
- Head: `feature/cutscenecity-twitch-vod-shorts` @ `8cbb605`
- Base: `master` @ `e973d51`
- Created: 22 Nov 2026, 10:16 AM IST (`2026-11-22T04:46:21Z`)
- Updated: 22 Nov 2026, 10:20 AM IST (`2026-11-22T04:50:52Z`)
- Body (summary): yt-dlp / FFmpeg / OpenCV review-only pipeline and a manually triggered Actions workflow. Originally tied to VOD `<VOD_ID>`. No YouTube publishing in that PR. Motion scoring is a heuristic. Rights review and a real VOD test are still required before merge.

### Local-only branches in `/workspace/gta6-automation/fork`

These four exist only on the box (not on the fork remotes, except as noted):

| Branch | Head | Purpose (commit subject) | Commit time (IST) |
|---|---|---|---|
| `gta6-originality` | `edd2ad1c817783c597dc7d17dd6de245ec9516f3` | Approval gates, reused-content, fact-check, disclosure, safer cadence | 16 Nov 2026, 2:27 AM IST (`2026-11-15 20:57:11 +0000`) |
| `gta6-human-style` | `cbe8426c26f662137d236390bf5feb27eea98c4a` | Human-style output: own edit/voice, frame-grab thumbnails, TTS opt-in | 16 Nov 2026, 2:49 AM IST (`2026-11-15 21:19:02 +0000`) |
| `gta6-ai-generation` | `0ea239d60914c20381ed220fe3ca670ed4011043` | AI voice/stills/clip switches, forced disclosure, Ken Burns assembly | 16 Nov 2026, 12:54 PM IST (`2026-11-16 07:24:21 +0000`) |
| `cutscenecity-phase1-tweaks` | last observed `6050263061e7bc157638091bdc097adb4f364c88` | Phase 1+2 tweaks plus later “phase 2.1” commit (see below). **Ahead of** `origin/feature/cutscenecity-twitch-vod-shorts` | see below |

`cutscenecity-phase1-tweaks` history observed on this box (do not assume this is still HEAD; another worker was committing):

1. `ccad4e84a3572c41a370ef01d4fad14fd5243b93` — Phase 1: multi-signal selection notes, 9:16 layouts + captions + loudnorm, default-deny compliance gates, signed review log, gated private upload package. **23 Nov 2026, 8:27 AM IST**.
2. `2099db338fcfde036df088f44ab037ea4942c793` — Phase 2: own-VODs-only (no default VOD), TTS counts only with forced synthetic disclosure, daily cap 1, blur default, Node ingest route `POST /api/gta6/external-shorts` with signed-package verification and per-upload approval click, token revoke. **23 Nov 2026, 10:03 AM IST**.
3. `6050263061e7bc157638091bdc097adb4f364c88` — “CutsceneCity phase 2.1: creator-owned gate 1 and commentary gate 4 v3”. Observed later the same morning as branch HEAD, **ahead 3**. Commit timestamp **UNVERIFIED** (not re-read after wrap-up was requested).

When first inspected, the worktree also had uncommitted edits under `tools/twitch-shorts/` and `utils/cutscenecity/`. Later the branch was clean at `6050263`. Treat the box copy as in motion.

### Remote `gta6-improvements` — do not merge

Head `548c4a5` (“Update GTA6 improvements status”), 16 Nov 2026, 1:58 AM IST (`2026-11-16 01:58:17 +0530`), author Sheb_zz.

`utils/gta6-private-upload-guard.js` contains:

```js
const forcePrivate = process.env.GTA6_FORCE_PRIVATE !== 'false';
```

Setting `GTA6_FORCE_PRIVATE=false` turns the private-upload force **off**. That is a bypass of the “uploads stay private” rule. There is also a `humanApprovedPublic` / `approvalToken` path. **Do not merge this branch into the CutsceneCity or production line.**

### Existing CutsceneCity work (already in progress)

Do not start from a blank repo. The clipping → review → private-upload path already exists locally:

- PR #1 code under `tools/twitch-shorts/` (pipeline, QA, render, editorial policy, GitHub workflow). Originally motion-heuristic, review-only, no publishing.
- Local phase 1 + 2 (+ observed 2.1) commits on `cutscenecity-phase1-tweaks`, documented in [`/workspace/gta6-automation/fork-patch/CUTSCENECITY-PHASE1.md`](fork-patch/CUTSCENECITY-PHASE1.md). Cumulative patches: `fork-patch/cutscenecity-phase1.patch`, `fork-patch/cutscenecity-phase2.patch`.
- Compliance gates (provenance / creator-owned Twitch, cutscene, audio/music, commentary share, overlay blur, spoiler, cap 1, duplicate, signed review, forced private, audit log). Some detectors are still basic / heuristic.
- Package handoff: `agent-import.json`.
- Node ingest: `POST /api/gta6/external-shorts` in `utils/cutscenecity/external-shorts.js` (on the local branch). Auth via `x-api-key`. Ingest never uploads. Approval is a separate click (`POST /api/gta6/external-shorts/:id/approve-upload` or `npm run cutscenecity:shorts -- approve`). Upload is private-only, `madeForKids` false, `containsSyntheticMedia` when TTS is used, no `publishAt`.
- Shared audit ledger: `CUTSCENECITY_STATE_DIR/upload-audit.jsonl`.
- Known residual risks from the phase-1 doc: the fork is **public**; the Actions workflow still uploads rendered clips as 3-day artifacts (Shebin chose to leave this). Real YouTube upload has only been mocked. Twitch owner login/ID was still pending when this eval was written. The handover “Mode A/B” rubric was never found.

The `cutscenecity-phase1-tweaks` line is based on PR #1 / `master`, **not** on `gta6-originality` → `gta6-ai-generation`. Those GTA6 branches remain separate and unpushed.

---

## 2. Clipper evaluations

Shallow clones (depth 50) are at:

- `/workspace/clippers/neonclipping`
- `/workspace/clippers/autoclip-zhouxiaoka`
- `/workspace/clippers/autoclip-artbyjazi`

No secrets were used. A full venv smoke-install was **not** run (wheels for `faster-whisper` / OpenCV / MediaPipe are not cheap, and this box is Python 3.13, which artbyjazi explicitly does not support). Install readiness is therefore **UNVERIFIED** beyond reading install scripts and requirements.

### 2.1 NeonClipping — `iamajmeena/neonclipping` — **best starting point**

| | |
|---|---|
| Exists / maintained | Yes. Created 19 Nov 2026. Last local commit `052500437bc8d44ed5c8311e8ce686373e098086`, **22 Nov 2026, 4:16 AM IST** (`2026-11-22 04:16:44 +0530`). API `pushed_at` `2026-11-21T22:46:46Z`. Very high recent commit rate (many commits on 21–22 Nov). |
| Stars / forks | **2,126** stars, 121 forks (API, 23 Nov 2026). Open issues: 30. |
| Licence | **MIT** (`LICENSE`, Copyright 2026 Ajay K Meena). |
| Language / stack | Python 3.10–3.13, FastAPI/Uvicorn, yt-dlp, FFmpeg, faster-whisper, OpenCV headless, Streamlink, pytchat, NumPy, Pillow. Optional Ollama (`llama3.2:3b` recommended) or any OpenAI-compatible cloud LLM. |
| What it does | Paste a YouTube / **Twitch** / Kick link or a local MP4 → ranked, captioned **9:16** clips with title + hook. Fast mode (default, videos >10 min) downloads **audio only** first, scores loudness jumps / raised voice / keywords, optionally asks a local LLM to score and write titles, then downloads **only the chosen video sections**. Deep mode adds optical-flow motion and cut density (downloads the whole file). 11 layouts including blur, crop, facecam overlays. 5 caption styles, 52 languages, SRT/VTT. Live clipping via Streamlink + chat-spike detection. “Creators” watcher can auto-record when a channel goes live. |
| Highlight method | Heuristic audio (loudness vs 2-min baseline, 2–4 kHz energy) + keyword list (EN/HI) + optional optical flow + optional local/cloud LLM on **transcript text only**. Learns from local star ratings (`data/feedback.jsonl`). README is explicit: this is not guaranteed “viral” detection, and the LLM cannot see the screen. |
| Paid APIs / keys | **Not required.** Works on audio/motion scores alone. Optional Ollama (local). Optional Cloud AI (Groq, OpenRouter, Gemini, OpenAI, LM Studio) — only candidate **text** is sent. Key stored in `data/llm.json` or `NEONCLIPPING_LLM_*` env vars. |
| Vertical / captions | Yes, burned-in, editable, 9:16 1080×1920. |
| Twitch input | **First-class.** README cites a 3-hour Twitch VOD Fast-mode run (136 s on an RTX 2060, maintainer measurement). Live Twitch + chat spikes tested. Twitch VODs have no YouTube captions, so a local Whisper model is required (slower on CPU). |
| Disk / GPU / RAM | Fast mode is disk-friendly (README: 79 MB audio for an 85-min video; then only selected sections). Unattended live watch stops if free disk < **8 GB** (`NEONCLIPPING_MIN_FREE_GB`). Deep mode on multi-hour VODs will need many GB. GPU optional: NVIDIA NVENC / CUDA whisper, else VideoToolbox or x264 CPU. Exact RAM need **UNVERIFIED**. Maintainer has **not** run the Mac installer on his own Mac. |
| Headless | **Web UI** at `http://127.0.0.1:8770` (`./run.sh`). No dedicated CLI, but a real HTTP API: `POST /make`, `GET /make/{job}`, `/library`, `/media/{id}`, `/upload`. Suitable for an adapter. Default bind is loopback; `NEONCLIPPING_LAN=1` binds `0.0.0.0` (PIN-protected phone remote). |
| Security | No `curl \| bash` of untrusted hosts in `install.sh` (it curls the official GitHub `main.zip`). Windows `NeonClipping-Setup.bat` can download `install.ps1` from `raw.githubusercontent.com` if the local file is missing — supply-chain note, not obfuscation. In-app updater pulls the GitHub zip; README says a **git checkout is never touched**. Server is loopback by default. Optional “Report a problem” is user-triggered. No telemetry/exfil hits in a pattern scan of 98 source files (one test mentions an analytics tag on the project site). No hardcoded live API keys found. Cloud keys in `data/llm.json` must stay off the repo and off notebooks. |
| Compliance clashes | Built-in **music bed** must be left **off** (our gates reject audible music). The **Creators** auto-watcher must not be pointed at anyone else’s channel (own VODs only). “No auto-posting” is already a stated non-goal — good. |

**Verdict:** Use this as the moment-finder / optional renderer. Best match for own Twitch VODs and gameplay layouts. Feed its outputs into our gates; do not let it publish.

### 2.2 AutoClip (zhouxiaoka) — `zhouxiaoka/autoclip`

| | |
|---|---|
| Exists / maintained | Yes, very active. Last local commit `49fa8e859e6573a5e32a9135502dfddcefd834cb`, **23 Nov 2026, 9:40 AM IST** (`2026-11-23 12:10:50 +0800`). Version in `pyproject.toml`: **1.5.9**. |
| Stars / forks | **13,668** stars, 2,150 forks. Open issues: 29. Homepage: https://zhouxiaoka.github.io/autoclip_intro/ |
| Licence | **MIT** (Copyright 2024 AutoClip Team). |
| Language / stack | Python 3.10+ (3.11 recommended), FFmpeg, desktop app (Tauri; macOS **Apple Silicon** and Windows x64 only), Docker/web UI, CLI / MCP. Local or cloud ASR (Whisper / SenseVoice / Bailian). Many LLM providers, Ollama, LM Studio. |
| What it does | “One link, one click” repurposing of **podcasts, interviews, courses, talking-head** video into Shorts / Douyin / TikTok / Reels, with captions, covers, and post copy. Cutting/rendering are local. Cloud analysis may send captions, post text, sample frames, or audio (if cloud ASR). |
| Highlight method | LLM / model analysis of captions (creator captions preferred; else local or cloud ASR). Visual understanding is optional and recommended by the README **for gameplay** — i.e. gameplay is not the validated default. |
| Paid APIs / keys | App is free. Cloud analysis, transcription, and AI images use **your** keys and are billed by the provider. Local Ollama/LM Studio need no key but need hardware. First local install downloads ~220 MB (README). |
| Vertical / captions | Yes. |
| Twitch input | **No first-class support found.** Import recovery code treats YouTube and Bilibili as the public sites. A “twitch” hit in tests is a variable name in framing math, not a Twitch downloader. Local files can be imported, so a pre-downloaded VOD could be fed in, but this is **UNVERIFIED** for long gameplay streams. |
| Disk / GPU / RAM | Desktop bundles Python/FFmpeg. CLI needs Python + FFmpeg, no Redis. Exact RAM/GPU figures **UNVERIFIED**. Intel Macs and Linux use Docker or CLI, not the desktop build. |
| Headless | **Yes:** `autoclip produce … --json`, MCP, and a Docker web UI (`localhost:3000` / API `:8000`). Good for agents, poor domain fit. |
| Security | Pattern scan is noisy because of tests and docs. Real flags: **PostHog anonymous analytics are on by default**; **Sentry crash reports are on by default** when a DSN is built in (disable under Settings → App). Privacy doc is dated 9 Oct 2026 and is marked a **“draft template”**. `Dockerfile.dev` uses `curl … nodesource \| bash` (Node install; dev image). Desktop installers are **unsigned** (issue #119); releases ship `build-provenance.json`. Test files contain fake `sk-` strings, not live keys. The app can **publish** to connected platforms — do not enable that. |

**Verdict:** Strong, maintained product, but built for talking-head repurposing, with default telemetry and no Twitch-native path. **Do not use as the CutsceneCity clipper.** Optional later reference for CLI/MCP patterns only.

### 2.3 AutoClip (artbyjazi) — `artbyjazi/autoclip`

| | |
|---|---|
| Exists / maintained | Exists, **stale**. Last commit `5d0eac36fa615b79dd2104083bf273a96f8d68bb`, **1 Aug 2026, 6:06 AM IST** (`2026-08-01 03:36:07 +0300`). API `pushed_at` `2026-08-01T01:08:38Z`. Pre-1.0 (`0.1.0.dev0`). About 3.5 months with no push as of this check. |
| Stars / forks | **530** stars, 195 forks. Open issues: 9. |
| Licence | **MIT** (Copyright 2026 Jad Ghazi). Bundled fonts: SIL OFL. |
| Language / stack | Python **3.11 or 3.12 only** (not 3.13; MediaPipe has no wheels). FastAPI + React UI, Typer CLI, yt-dlp, faster-whisper, MediaPipe, scenedetect, optional WhisperX diarization (gated HF models + token). |
| What it does | YouTube URL or local file → transcribe → LLM highlight (word indices, not timestamps) → speaker-tracked 9:16 reframe → burned captions. Review UI + `autoclip clip` CLI. Fully local with Whisper + Ollama, or BYO Anthropic/OpenAI/Gemini/compatible key (transcript text only). |
| Highlight method | LLM over the transcript. Clip *quality of picks* is explicitly unverified by the author. Reframe is designed for **talking-head / multi-speaker**, not facecam-plus-gameplay. |
| Paid APIs / keys | Not required if Ollama is used. Cloud keys go in the OS keyring (fallback file is disclosed). Diarization needs a Hugging Face token. |
| Vertical / captions | Yes (four styles). Exports also mention AAC at −14 LUFS. |
| Twitch input | **No.** Ingest types are `youtube` and `upload` only. A pre-downloaded own-VOD MP4 would work as an upload; Twitch URLs are rejected. |
| Disk / GPU / RAM | Work dir `~/.autoclip/`. GPU optional (CUDA extra; macOS uses CPU path). Diarization pulls PyTorch (large). Exact RAM **UNVERIFIED**. |
| Headless | **Yes.** First-class CLI (`autoclip doctor\|serve\|clip`) plus a local web UI on `127.0.0.1:8000`. No auth — must stay on loopback (`SECURITY.md`). |
| Security | Clean scan (87 files): no pipe-to-shell, no telemetry (README/SECURITY claim no phone-home; scan agrees), no hardcoded secrets. Sensible security doc. |

**Verdict:** Well-designed local-first CLI, but stale, talking-head focused, no Twitch URLs, and incompatible with Python 3.13. **Not the starting clipper.** A local MP4 could be a fallback only if Neon is unavailable.

### 2.4 Other strong OSS clippers (not cloned)

1. **[Anil-matcha/AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator)** (GitHub also redirects from the older `SamurAIGPT/AI-Youtube-Shorts-Generator` name already noted in `TWITCH-SHORTS-RESEARCH.md`). MIT. **6,477** stars, 1,191 forks. Last push `2026-11-21T12:34:29Z` = **21 Nov 2026, 6:04 PM IST**. Actively maintained. CLI + `--output-json`, local mode with yt-dlp / faster-whisper / ffmpeg / OpenCV face-track, or **default `--mode api` which uses paid MuAPI**. Highlights are LLM-ranked “virality” features. YouTube-oriented; not a Twitch-native gameplay tool. Promotes a paid clipping API in the README. Useful as a JSON-shaped reference, **not** as the primary CutsceneCity engine, and not in API mode (keys/cost + off-machine media).

2. **[haziqahmedqasmi/PeakCut](https://github.com/haziqahmedqasmi/PeakCut)**. MIT. **1,767** stars, 552 forks. Last push `2026-11-20T13:52:57Z` = **20 Nov 2026, 7:22 PM IST**. Brand new (created 14 Nov 2026). YouTube / **Twitch** / Kick + live clipping, captions, hooks. Neon’s README says it studied PeakCut’s audio-first design. **Do not use its posting features** (YouTube / Instagram / TikTok queue or auto-post). Can run with no key (loudness only) or BYO LLM. Runner-up to watch; Neon is the better starting point because it is already cloned, has a documented Fast-mode Twitch VOD path, facecam layouts, and an HTTP API that we can adapt without enabling publish.

`curtyo18/ClipCutter` (also mentioned by Neon) has 1 star and no licence on the API payload — skip.

---

## 3. Hosting (Mac almost out of space)

Context: multi-GB Twitch VODs, Whisper on VOD audio, FFmpeg 9:16 renders, then a long-lived Node agent (`127.0.0.1:3456`) holding a YouTube **OAuth refresh token**. That token and all API keys must stay **out of notebooks, chat, and the git repo**.

### GitHub Codespaces (verified 23 Nov 2026 from official docs)

Sources: [Codespaces billing](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces), [included usage](https://docs.github.com/en/billing/reference/product-usage-included).

- GitHub Free (personal): **15 GB-month storage + 120 core-hours / month**. A 2-core machine burns 2 core-hours per hour ≈ **60 hours** of 2-core time (GitHub’s own wording).
- GitHub Pro: **20 GB-month + 180 core-hours**.
- Overage (official table): compute **$0.18/hr** (2-core) … **$2.88/hr** (32-core); storage **$0.07/GB-month**. Storage accrues **while the codespace exists, including stopped**.
- If no payment method is on file, usage is **blocked** when the quota is exhausted.
- 2-core VM disk is typically 32 GB (from prior `HOSTING.md` / GitHub machine-size docs, 16 Nov 2026; not re-opened this pass — treat disk-size table as **UNVERIFIED today**).
- Shebin has already hit Codespaces **storage** problems. A codespace holding ~20 GB of VOD for a month is already over the 15 GB-month Free allowance.
- OAuth: forwarded URL is `https://…app.github.dev`, which is **not** a loopback redirect. Auth on the Mac, copy `tokens.json` in if this is ever used. Keep port 3456 **private**.

**Not suitable** as the VOD + clipping + agent host.

### Google Colab (official FAQ + ToS, fetched 23 Nov 2026)

Sources: [Colab FAQ](https://research.google.com/colaboratory/faq.html), [Colab Additional Terms](https://research.google.com/colaboratory/tos_v6.html) (last modified 13 Aug 2026).

- Free of charge, but resources are **not guaranteed**, limits **fluctuate**, and GPU access in the free tier is **heavily restricted**. Exact free GPU hours and idle-timeout minutes are **not published** (official: “usage limits sometimes fluctuate”; VMs “are deleted when idle for a while, and have a maximum lifetime enforced”). Third-party 2026 guides often say a **12-hour** cap — **UNVERIFIED** in the FAQ text captured this pass.
- Free managed runtimes may be terminated without warning for SSH/remote desktop, **bypassing the notebook UI to drive a web UI**, or similar. Neon’s UI and a long-running Node dashboard fit that pattern.
- Disallowed on all managed runtimes: file hosting / media serving not related to interactive notebook compute, torrents, proxies, multi-account quota bypass.
- You must accept those FAQ limits under the ToS. Account sharing is forbidden.
- Persistence is typically Google Drive; a VOD + models can blow Drive/quota, and a disconnect wipes the VM disk. **Do not put OAuth refresh tokens or API keys in a notebook, Drive-shared file, or Colab secret that gets pasted into cells.**

**Not suitable** for VOD download, a clipping web UI, or the Node agent.

### Kaggle notebooks (official docs, fetched via docs pages 23 Nov 2026)

Source: [Kaggle Notebooks](https://www.kaggle.com/docs/notebooks), [efficient GPU usage](https://www.kaggle.com/docs/efficient-gpu-usage).

- Session cap: **12 hours** CPU/GPU, **9 hours** TPU.
- Saved disk: **20 GB** in `/kaggle/working`. Scratch outside that path is deleted when the session ends. 20 GB is tight for a multi-hour Twitch VOD plus models plus renders.
- GPU weekly quota: official wording **“30 hours or sometimes higher depending on demand and resources”**, resets weekly, not guaranteed (queues possible).
- Official notebooks page still lists a P100 SKU; some 2026 secondary sources say P100 was retired for T4 x2 on 15 Sep 2026 — **UNVERIFIED conflict**. Use whatever the account Settings page shows.
- Interactive idle timeout is **20 minutes** in the notebooks doc; the GPU-tips page also mentions 60 minutes — **conflict, treat 20 minutes as the safe figure**.
- Same secret rule as Colab. No long-lived private dashboard.

**Not suitable** as the always-on agent host. A one-off Whisper experiment is the most it is good for, and even that is a tight fit for VOD size.

### Cheap India VPS (prices last fetched 16 Nov 2026 in `HOSTING.md`; **not re-priced today — treat INR and exact SKUs as UNVERIFIED today**)

From [`HOSTING.md`](HOSTING.md):

- **DigitalOcean Basic Droplet, Bangalore:** 2 GiB / 1 vCPU / **50 GiB** / 2,000 GiB transfer, **$12/mo**.
- **Vultr Cloud Compute, Mumbai** (also Bangalore / Delhi NCR / Chennai): list **$10/mo** (1 vCPU / 2 GB / 55 GB / 2 TB) or **$12/mo** High Frequency. Confirm the Mumbai quote in the console; Vultr warns prices can differ by location.
- Persistent disk, included transfer far above this channel’s upload volume, SSH/Tailscale so port 3456 never goes public.
- OAuth: one-time **Desktop** client flow on the Mac (`http://127.0.0.1`), then `scp` `config/credentials.json` and `config/tokens.json` with mode **600**. Do not run the consent flow through a public URL.
- GST / tax treatment in India: **UNVERIFIED**.

### Hosting recommendation

**Use a small India-region VPS** (prefer DigitalOcean Bangalore at $12/mo, or Vultr Mumbai at the $10–$12 list price after a console check) for:

1. **VOD download** (yt-dlp; delete the full file after section clips are cut — Neon Fast mode helps),
2. **Clipping** (NeonClipping + our `tools/twitch-shorts` gates),
3. **Node agent** (ingest route + approval UI over `ssh -L 3456:127.0.0.1:3456`).

Do **not** use Codespaces as the daily host (storage quota; Shebin already hit this). Do **not** use Colab or Kaggle for the pipeline or the OAuth-bearing agent (session wipe, ToS, 20 GB save cap, secrets in notebooks). Keep masters off the Mac if the SSD is full; rsync only the current package; delete after a successful private upload. Auth stays on the Mac.

---

## 4. Minimal wiring

External clipper **feeds** candidate selection. It does **not** replace our gates, signed review, ingest, approval click, or private upload.

```
own Twitch VOD (yt-dlp or Neon Fast-mode URL)
        → NeonClipping  (moment scores; optional 9:16 render; music bed OFF)
        → adapter       (timestamps, title/hook, paths, provenance)
        → tools/twitch-shorts gates
              provenance / broadcaster-ID owner match,
              cutscene, audio/music, commentary (≥60%),
              overlay blur, spoiler, cap 1, duplicate,
              signed human review
        → agent-import.json
        → POST /api/gta6/external-shorts
        → human approval click
        → private YouTube upload
```

### Adapter (to build next; not built in this pass)

A small script, on the VPS, that:

1. Ensures `OWNER_TWITCH_LOGIN` / broadcaster ID is set and rejects any other channel (already the local gate policy).
2. Calls Neon `POST /make` with the VOD URL or a local path, then polls `GET /make/{job}` until clips appear.
3. Copies each MP4 (and SRT if present) plus start/end, title, hook, and Neon’s score/reason into a package directory under `CUTSCENECITY_PACKAGES_DIR`.
4. Writes provenance: VOD URL, stream date, clip timestamps, owner broadcaster ID.
5. Runs the existing Python review/gate path (or `pipeline.py` in a “pre-selected candidates” mode). Prefer **our** `render.py` (default **blur** layout, loudnorm, overlay blur) if Neon’s render would include a music bed or skip chat-crop. Using Neon’s MP4 is acceptable only after the audio/music and overlay gates still run and pass.
6. Emits `agent-import.json` in the schema the Node route already validates.
7. Ingests with `npm run cutscenecity:shorts -- ingest …` and stops. Upload happens only after Shebin’s approve click.

Do not wire Neon’s live “Creators” watcher, PeakCut/Zhou publishing, or MuAPI. Do not merge `gta6-improvements`. Do not put tokens in Colab.

### Still blocked (unchanged)

- Shebin’s Twitch login / broadcaster ID was not in hand at write time.
- `cutscenecity-phase1-tweaks` is local-only; push to the fork was approved earlier but had no GitHub login on this box — **not done here**, and this task forbids pushes.
- Real private upload still untested (mocks only).
- Public-fork + 3-day CI clip artifacts remain as previously chosen.

---

## 5. Next five steps

1. **Set owner identity** — Shebin supplies his Twitch login and broadcaster ID; put them in the CutsceneCity env (`OWNER_TWITCH_LOGIN` / whitelist). Until then the provenance gate must keep failing closed.
2. **Stand up the VPS** — DigitalOcean Bangalore ($12) or Vultr Mumbai ($10–$12, confirm in console). Install Python 3.12, FFmpeg, Node ≥18.17, git. Clone Neon from `/workspace/clippers/neonclipping` (or `git clone` the upstream tag/`main`). Run `./run.sh` bound to 127.0.0.1 only. Do not install this on the nearly-full Mac.
3. **Copy the local pipeline, not a new rewrite** — take `cutscenecity-phase1-tweaks` (after the other worker finishes) onto the VPS as a private working copy. Do not push or open PR comments until Shebin again says “push”. Keep `gta6-improvements` unmerged.
4. **Write the Neon → `agent-import.json` adapter** and test it on a **short, already-owned** local MP4 (no real YouTube upload): Neon `/make` → gates all fail-closed until commentary + signed review are present → ingest route accepts a dry package.
5. **One private test upload** — Desktop OAuth on the Mac, `scp` tokens (mode 600) to the VPS, SSH tunnel to `:3456`, approve one package, confirm `privacyStatus=private` in Studio, then revoke is available if needed. Only after that consider a daily cap-1 schedule.

---

## 6. What was and was not done in this pass

- Cloned the three requested repos under `/workspace/clippers/`.
- Did not modify `/workspace/gta6-automation/fork`, did not check out branches there, did not push, did not comment on PR #1, did not submit any API audit, did not upload.
- Did not run a venv smoke-install or any command with API keys.
- Did not clone Anil-matcha or PeakCut (README/API only).
