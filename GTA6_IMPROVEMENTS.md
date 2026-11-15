# GTA 6 YouTube Automation Improvements

## Status (as of 16 Nov 2026)
- Branch `gta6-improvements` created.
- Private upload guard utility added: `utils/gta6-private-upload-guard.js`
- Local clips provider example added: `utils/local-clips-provider.example.js`
- Example config added: `config/gta6-local-clips.example.json`

## Core Safety Rules
- All uploads default to **private**. Human must manually switch to public or set publishAt.
- Never auto-publish without explicit approval gate.
- Local gameplay clips preferred over stock/AI footage for originality.
- Compliance checklist must pass before any upload.

## Next Steps
1. Wire the private upload guard into `agents/publishing-scheduling-agent.js`.
2. Implement full LocalClipsProvider and point video generation at `./gta6-clips`.
3. Add the 15-point compliance checklist as a pre-upload gate.
4. Disable stock video providers by default.
5. Add GTA 6 specific prompt templates.
6. Test with a private synthetic upload once YouTube API credentials are configured.

Forked from darkzOGx/youtube-automation-agent for GTA 6 channel use.
