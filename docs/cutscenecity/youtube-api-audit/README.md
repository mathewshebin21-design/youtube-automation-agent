# CutsceneCity: YouTube API Services audit / quota-extension package (DRAFT, not submitted)

**Status: not submitted.** Shebin submits it himself, if he decides it's needed. Nothing here was sent anywhere.

## Read first: you probably don't need to submit this yet
The rule that made unaudited uploads private-only has been reversed.

- **[VERIFIED]** The official YouTube Data API Revision History entry for **November 2, 2026** says: "Videos uploaded through the `videos.insert` method from unverified API projects are no longer restricted to private viewing mode." It reverses the July 28, 2020 policy. Source: https://developers.google.com/youtube/v3/revision_history (fetched 23 Nov 2026).
- **[VERIFIED]** The `videos.insert` reference (last updated 2026-11-12) now says that if `status.privacyStatus` is omitted, the video **defaults to public**. CutsceneCity code always sends `private` explicitly, so this doesn't affect us, but never remove that line.
- **[VERIFIED]** Default quota is 100 `videos.insert` calls per day plus 10,000 units per day for other endpoints. An audit is required only to get **more** than that. Source: https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits (last updated 2026-11-12).
- The CutsceneCity daily cap is **1 upload a day**, which is far below the default quota.

**Recommendation:** finish private testing first. Submit this form only if:
- you later need more than the default quota; or
- YouTube asks for a periodic audit.

The earlier Phase 1 doc said unaudited uploads would be private-locked. That is now out of date, and the Phase 2 doc corrects it.

## Files
| File | What it is |
|---|---|
| `form-draft-answers.md` | Field-by-field draft answers for the Audit and Quota Extension Form |
| `use-case.md` | Use-case and justification text to paste |
| `data-handling.md` | Data-handling summary: what is accessed, stored, for how long, and how it is revoked |
| `privacy-policy-draft.md` | Draft privacy policy. The Developer Policies require one, published at a public URL |
| `screencasts.md` | The screencasts and screenshots Shebin must record |

## When you do submit (order)
1. Finish at least one private test upload end to end. Use the Phase 1 doc §6, or the Phase 2 Node route.
2. Publish the privacy policy and terms at a public URL. For example, a GitHub Pages page on the fork, or a page on your own site.
3. Record the screencasts in `screencasts.md` and upload them as **unlisted** videos or Drive links (viewable by anyone with the link).
4. Fill in the form at https://support.google.com/youtube/contact/yt_api_form using `form-draft-answers.md`.
5. Keep a copy of everything you submitted.
