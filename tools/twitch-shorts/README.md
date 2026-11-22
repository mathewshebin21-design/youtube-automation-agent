# CutsceneCity Twitch → Shorts integration (review-only prototype)

Source VOD: https://www.twitch.tv/videos/2936544559
Destination: YouTube CutsceneCity (@cutscenecity), connected separately through vidIQ.

Run GitHub Actions workflow **CutsceneCity Twitch VOD Shorts (review only)** manually after merging this PR. The job downloads a public VOD using yt-dlp, ranks 35-second candidate windows by motion, renders 9:16 letterboxed MP4s and uploads review artifacts. It does **not** upload to YouTube, schedule videos, or enable autonomous external actions.

## Limitations and release gates
- Motion is not semantic understanding: a human must watch and approve each selected scene.
- VOD playback/download can fail due to Twitch availability, age gates, authentication or restrictions.
- GitHub Actions hosted runners have storage, time and artifact size limits; a one-hour VOD may exceed them.
- Original broadcast rights do not automatically grant game publisher or music rights.
- Rendering preserves the full frame via letterboxing rather than cutting off HUD or story action.
- Before connecting this to the existing YouTube agent publishing pipeline: validate real clips, review game/music rights, confirm channel OAuth scope, obtain approval for exact media and metadata, and test a private upload.
- Never commit Twitch cookies, OAuth tokens, Google credentials or large VOD files.
