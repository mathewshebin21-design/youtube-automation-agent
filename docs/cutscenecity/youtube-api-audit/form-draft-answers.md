# Draft answers: YouTube API Services Audit and Quota Extension Form

- **Form:** https://support.google.com/youtube/contact/yt_api_form (fetched 23 Nov 2026).
- **How to read the tags:**
  - **[VERIFIED]** means the field label or instruction was visible on the live form page I fetched.
  - **[UNVERIFIED]** means the field is dynamic (it only appears after selections or sign-in) or its exact wording wasn't visible, so check it on the live form.
- Replace every `<...>` placeholder yourself. Never put passwords for your real channel account in this form.

## Section 1: Request type
**[VERIFIED] "Select the reason for your request".** The options are:
- "Complete a compliance audit to request for additional quota"
- "Complete a compliance audit to keep current quota (requested to complete re-audit)"

Draft answer:
- If you need more quota, choose **option 1**.
- If YouTube asked you to re-audit, choose **option 2**.
- If you only want an audit on record with no extra quota:
  - **[UNVERIFIED / community guidance]** In Google Issue Tracker #558966907 (Sep 2026), a Google staff reply said to choose option 1 and then "No change / Default quota". It also gave the values 100 per day and 1 per minute, plus a fixed justification sentence. That thread was about lifting the private-only restriction, which has since been reversed (see README).
  - Confirm with YouTube API support before you rely on this.

## Section 2: Contacts and organisation
| Field | Status | Draft |
|---|---|---|
| Legal name of primary contact | [VERIFIED] | `<Shebin Mathew's legal name>` |
| Organisation legal name ("If applying as an individual please write 'self'") | [VERIFIED] | `self` |
| Primary contact details | [VERIFIED] | `<email you check>`, `<phone optional>` |
| Technical contact | [VERIFIED] (optional) | Same as primary, or leave blank |
| Google Ads Customer ID(s) | [VERIFIED] (only if you manage ads for others) | Leave blank / "N/A – I do not manage ad campaigns for others" |

## Section 3: API client
| Field | Status | Draft |
|---|---|---|
| Application name | [VERIFIED] | `CutsceneCity Uploader (self-hosted, single channel)` |
| Main URL where the client can be accessed | [VERIFIED] | `https://github.com/mathewshebin21-design/youtube-automation-agent` (source code). Say it is a self-hosted local tool with no public web app |
| Test credentials with full access | [VERIFIED] | "This is an internal, self-hosted, single-user tool that runs only on the owner's computer at 127.0.0.1. There is no hosted login or demo account. An end-to-end screencast is provided in Section 6 as the form instructs for internal-only tools." **Do not give your real Google password.** |

## Section 4: Project (one per Google Cloud project; up to 10)
| Field | Status | Draft |
|---|---|---|
| Google Cloud Project Number | [VERIFIED] (digits only) | `<project number from Cloud Console Welcome card>` |
| Use Case Category | [VERIFIED] (the label is visible; option names are dynamic) | The category described as "tools that assist users with video uploads, editing metadata (like titles)…", i.e. Video Uploading & Account Management. Possibly also "Internal Company Tool" [UNVERIFIED wording] |
| Feature details (expand per use case) | [UNVERIFIED] (dynamic) | Paste from `use-case.md` |
| Required evidence: OAuth flow screenshots (consent screen, scopes, revocation) | [VERIFIED] | Screencast/screenshots A1–A3 in `screencasts.md` |
| Required evidence: upload interface screenshots | [VERIFIED] | B1–B4 |
| Required evidence: privacy policy screenshots (YouTube sections, Google Privacy Policy link, deletion policies) | [VERIFIED] | Screenshots of the published `privacy-policy-draft.md` |
| Endpoints used | [VERIFIED] (label) | `videos.insert` only (the Python uploader and the Node route). If you later add captions or thumbnails, add `captions.insert` / `thumbnails.set` |
| Total per day quota | [VERIFIED] (required) | `100` (the default; we use at most 1 per day). Ask for more only if you really need it |
| Peak per minute quota | [UNVERIFIED] (seen only in the issue-tracker thread) | `1` |
| Detailed justification | [VERIFIED] | Paste "Justification" from `use-case.md` |

## Section 6: Additional evidence
**[VERIFIED].** The form says internal-only tools without a demo account must give an end-to-end screencast link here. Draft: links to screencasts A and B (unlisted YouTube or a Drive link anyone can view). Include a short note that the client never publishes publicly and only uploads private videos after a human approval.
