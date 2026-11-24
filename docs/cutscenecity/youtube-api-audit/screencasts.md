# Screencasts and screenshots Shebin must record

Record them on the Mac with QuickTime (File → New Screen Recording).
- Upload each as an **unlisted** YouTube video, or share it as a Drive link that anyone can view.
- Blur or hide the client secret, tokens, API keys, `CUTSCENECITY_REVIEW_KEY` and your email where possible. Never show `.env` or `~/.cutscenecity/env` on screen.

| ID | What to show | Why the form needs it |
|---|---|---|
| A1 | **OAuth consent flow, start to finish.** Run `python upload_private.py upload … --execute` with no token yet. The browser opens on 127.0.0.1, then Google's consent screen shows the app name and the **youtube.upload** scope. Pick the CutsceneCity account and allow it. | "OAuth Flow Screenshots: consent screen, scopes" [VERIFIED field] |
| A2 | Google Cloud Console → OAuth consent screen: app name, Testing/Production status, test user, scopes list | Shows the exact scopes |
| A3 | **Revocation.** Run `python upload_private.py revoke` and show the output. Then open https://myaccount.google.com/permissions and show the app is gone. | "…revocation" [VERIFIED field] |
| B1 | Review flow: `review.py status` showing blocking checks, the three `signoff` commands, then `approve` | Shows the human approval gate |
| B2 | `upload_private.py check` and a dry run showing the request body: `privacyStatus: private`, `selfDeclaredMadeForKids: false`, `containsSyntheticMedia`, no `publishAt` | Upload interface |
| B3 | **The approval click:** `--execute --confirm <code>`, or the Node route `npm run cutscenecity:shorts -- approve <id>` with name and confirm code, then the "Uploaded PRIVATE" message | Upload interface plus human control |
| B4 | YouTube Studio → Content: the new video shows **Private**. Open its Details to show Audience = not made for kids and the altered-content answer. | Proves private-by-default |
| B5 | A blocked case: `approve-upload` refused because of the daily cap or a duplicate | Shows the abuse limits |
| C1 | Screenshot of the published privacy policy page: the YouTube API Services sentence, Google Privacy Policy link, deletion and revocation sections | "Privacy Policy Screenshots" [VERIFIED field] |
| E2E | One continuous 3–6 minute recording: A1 → B1 → B3 → B4 | Section 6: internal tools without a demo account must give an end-to-end screencast [VERIFIED] |
