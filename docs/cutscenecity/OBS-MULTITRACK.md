# OBS multitrack setup for CutsceneCity (separate mic track)

A **separate creator mic track is required** (phase 2.7). Since phase 2.8 there is no mixed-track opt-in at all: `CUTSCENECITY_ALLOW_MIXED_TRACK` was removed. Captions are only ever transcribed from that mic track, and game audio is KEPT by default under the mic (phase 2.8 override; `--strip-game-audio` is the opt-in). This page collects the OBS facts already in the repo docs (`tools/twitch-shorts/README.md` phase 2.3 and `CUTSCENECITY-PHASE1.md` §5 and §11).

## Why
- A downloaded Twitch VOD has **one mixed audio track**. The Twitch VOD Track setting only chooses *what* goes into the VOD; the mic is not stored separately. VOD <VOD_ID> probed as 1 video + 1 stereo audio stream (ffprobe, phase 2.3). So commentary can't be measured, and mic-only captions can't be made, from the VOD.

## OBS facts
- **Twitch VOD Track:** by default, track 1 is the live audio feed and track 2 is the VOD audio feed. A source left off track 2 isn't in the Twitch VOD. Tracks 3-6 are free. It's set under Settings → Output → Twitch VOD Track (the Twitch account must be connected under Settings → Stream). VERIFIED in phase 2.3 against the OBS knowledge base "Twitch VOD Track Guide" (obsproject.com/kb/twitch-vod-track-guide); not re-checked in 2.7.
- UNVERIFIED (community reports only): Twitch Enhanced Broadcasting or a third-party "soundtrack" plugin can override the VOD Track routing. Check one test VOD after any OBS change.

## Recommended local recording (the mic on its own track)
1. Settings → Output → Recording → Audio Track: tick **1 + 3** (1 = full mix, 3 = mic only).
2. Edit → Advanced Audio Properties: put the **mic on track 3 only**, and game/desktop audio on track 1 without the mic, so the mic isn't doubled.
   - The phase 1 guide used tracks 1 + 2 with the mic on track 2. Either works as long as the mic is alone on one track. UNVERIFIED which layout Shebin's OBS uses today: probe a recording first.
3. Find the 0-based audio stream index of the mic: `ffprobe -v error -select_streams a -show_entries stream=index:stream_tags=title -of compact <recording>.mkv` (`0:a:0` = track 1, `0:a:1` = the next ticked track).
4. Render the clip with the mic stem:
   - `python pipeline.py --input <recording>.mkv --info-json vod.info.json --render --window START-END --mic-stream 1` (phase 2.8: the first render is already `mix` = game audio + mic; without `--mic-stream`/`--mic` it keeps only the source audio and the commentary gates fail)
   - `python review.py commentary --clip short_01.mp4 --mic-stream 1 [--audio voiceover.wav]` (phase 2.8: game audio KEPT by default under the mic at 1.0; `--strip-game-audio` removes it)
   - `python review.py edit --clip short_01.mp4 --by NAME` (default clean + captions, transcribed from the mic stem)
   - A separate mic file recorded on the VOD timeline also works: `--mic mic.wav`.

## Gates this feeds
`original_commentary` (60% coverage measured on the mic + TTS bus), `live_reaction_preserved` (mic at gain 1.0, never ducked), the captions mic-source check, `captions_reviewed`, and the phase 2.8 audio profanity scan (`profanity_audio_reviewed`, optional `--bleep tone|mute`).
