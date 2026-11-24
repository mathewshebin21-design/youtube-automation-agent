# Data-handling summary

| Data | Where | How long | Notes |
|---|---|---|---|
| OAuth client JSON (Desktop client) | `~/.cutscenecity/client_secret.json` on the owner's Mac (chmod 600) | Until the owner deletes it | Never committed to git; `.gitignore` covers it |
| OAuth token (refresh/access) | `~/.cutscenecity/token.json` (chmod 600) | Until revoked | `python upload_private.py revoke` revokes it at Google and deletes it locally. You can also revoke at https://myaccount.google.com/permissions |
| Data from the YouTube API | Only the `videos.insert` response: video ID and privacy status | The video ID is kept in the local audit log as a record of the owner's own action | No other YouTube data is fetched or stored. **[VERIFIED policy]** Developer Policies III.E.4: authorized data may be stored no longer than 30 days unless refreshed, and data must be deleted within 30 days of revocation. Keeping only the owner's own upload IDs needs a retention note in the privacy policy. Treat as **[UNVERIFIED]** whether IDs fall under an exception |
| Review log, upload audit log | Local files on the Mac | Owner-controlled | Contain names, hashes, timestamps and video IDs. No Google user data beyond the owner's own video IDs |
| Media (clips, VODs) | Local disk; GitHub Actions artifacts (3-day retention) if the CI workflow runs | Owner-controlled | Owner's own streams only |
| Third parties | None, except optional Gemini frame review in CI (frames of the owner's own footage, when a key is set) | – | Disclose in the privacy policy if used |

No user other than the channel owner ever authorizes the client, and no data is shared with or sold to anyone.
