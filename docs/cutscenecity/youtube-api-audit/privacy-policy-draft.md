# CutsceneCity Uploader: Privacy Policy (DRAFT; publish at a public URL before submitting)

_Last updated: <date>_

CutsceneCity Uploader ("the tool") is a self-hosted tool used only by its owner, <Shebin Mathew>, to upload videos to the owner's own YouTube channel.

**YouTube API Services.** The tool uses YouTube API Services. By using the tool you agree to be bound by the YouTube Terms of Service: https://www.youtube.com/t/terms. Google's Privacy Policy applies to data handled by Google: http://www.google.com/policies/privacy.

**What the tool accesses.** With your permission (scope `youtube.upload`), the tool uploads video files and their title, description, tags and settings to your channel. It doesn't read your other YouTube data.

**What the tool stores.**
- Your OAuth token, on your own computer only.
- A local log of uploads: file fingerprints, timestamps, the video ID and the privacy status YouTube returned.

Nothing is stored on any server operated by the developer.

**Sharing.** No data is shared, sold or transferred to third parties.

**Retention and deletion.**
- Running `upload_private.py revoke` deletes the token immediately.
- Local logs are kept until you delete them.
- If authorization is revoked, any stored API data is deleted within 30 days.

**Revoking access.** You can revoke the tool's access at any time at https://security.google.com/settings/security/permissions or by running `python upload_private.py revoke`.

**Cookies.** The tool doesn't use cookies or tracking.

**Contact.** <email> for questions or complaints about these privacy practices.
