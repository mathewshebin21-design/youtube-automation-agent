# GTA 6 YouTube Automation Improvements

## Core Safety Rules (Implemented / To Enforce)
- All uploads default to **private**. Human must manually switch to public or set publishAt.
- Never auto-publish without explicit approval gate.
- Local gameplay clips preferred over stock/AI footage for originality.
- Compliance checklist must pass before any upload.

## Recommended Changes
1. Force `privacyStatus: 'private'` in `uploadToYouTube` regardless of schedule (override only via explicit flag after approval).
2. Add LocalClipsProvider that reads from a `/gta6-clips` folder with a manifest.json.
3. Integrate the 15-point pre-publish checklist from Compliance bot.
4. Add GTA 6 specific prompt templates for Script & Strategy agents.
5. Disable stock video providers by default.

## Next Implementation Steps
- Update publishing agent to hard-enforce private uploads.
- Create local clips provider.
- Add compliance gate hook.
- Test with a synthetic private upload (no GTA footage).

Forked from darkzOGx/youtube-automation-agent for GTA 6 channel use.
