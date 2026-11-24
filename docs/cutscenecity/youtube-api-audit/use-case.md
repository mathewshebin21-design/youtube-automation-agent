# Use case and justification text (paste-ready)

## Short description
CutsceneCity Uploader is a self-hosted, single-user tool. It runs on the channel owner's own computer and uploads short gameplay clips from the owner's **own** Twitch streams to the owner's **own** YouTube channel (CutsceneCity). It is not offered to other users.

## How it works
1. The owner runs a local script that suggests candidate moments from his own Twitch VOD. Nothing is sent to YouTube at this stage. Before anything is downloaded, the script checks the VOD's public metadata against the owner's configured Twitch login and refuses any VOD from another channel.
2. The owner records his own commentary, writes the title and description (the description always credits the source stream and links the VOD), and signs off each compliance check in a signed local review log:
   - rights to the footage;
   - no story cutscenes;
   - music risk;
   - commentary coverage;
   - spoilers;
   - AI disclosure.
3. The owner approves the exact file and metadata. The tool then makes one `videos.insert` call with:
   - `privacyStatus=private`;
   - `selfDeclaredMadeForKids=false`;
   - `containsSyntheticMedia` set explicitly (forced true if any AI voice or visuals were used);
   - no `publishAt`.
4. The owner reviews the private video in YouTube Studio and decides there, by hand, whether to publish it.

## Justification
"Single-channel, self-hosted uploader used only by the channel owner for his own content. It makes at most one `videos.insert` call per day (enforced by a hard daily cap in code) and uses no other endpoints. Every upload is private, needs an explicit human approval of the exact file and metadata, and is recorded in a local audit log. The tool never publishes publicly or schedules publication. We request the default quota (100 `videos.insert` calls per day) and no increase."

If you ever request an increase, replace the last sentence with the real number and why you need it. Don't inflate it.

## Scopes
- `https://www.googleapis.com/auth/youtube.upload` only (Python uploader).
- The existing Node agent uses its own credential setup. Check its consent screen and list exactly the scopes it requests. **[UNVERIFIED]:** I didn't check the scopes on master's CredentialManager.
