"""Phase-1 tests: signals, layouts, default-deny gates, signed log, gated private upload (mocked; no network)."""
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("CUTSCENECITY_UPSCALE", "off")  # keep the suite fast; Upscale tests cover the 2160 default
import compliance  # noqa: E402
import gatelog  # noqa: E402
import render  # noqa: E402
import review  # noqa: E402
import signals  # noqa: E402
import upload_private  # noqa: E402

KEY = "k" * 40
HAS_FFMPEG = shutil.which("ffmpeg") is not None


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make_vod(path, seconds=60):
    # quiet tone with a loud burst at 40-46s; 16:9 test pattern
    ffmpeg("-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=180:duration={seconds}",
           "-filter_complex", "[1:a]volume='if(between(t,40,46),1.0,0.02)':eval=frame[a];[2:a]volume=0.3[mic]",
           "-map", "0:v", "-map", "[a]", "-map", "[mic]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path))
    # stream 0:a:0 = game/music mix, 0:a:1 = creator mic (OBS multitrack layout)


def good_clip(**over):
    c = {"file": "short_01.mp4", "start": 0.0, "end": 20.0,
         "provenance": {"source_platform": "twitch", "source_url": "https://www.twitch.tv/videos/1234567890",
                        "source_channel_name": "CutsceneCity", "source_channel_id": "cutscenecity",
                        "source_owner": {"vod_id": "1234567890", "uploader": "CutsceneCity", "uploader_id": "cutscenecity",
                                         "channel": None, "channel_id": None, "tool": "yt-dlp -J"}},
         "metadata": {"title": "This getaway went sideways fast", "privacyStatus": "private",
                      "description": "My take on a wild chase. Clip from CutsceneCity: https://www.twitch.tv/videos/1234567890",
                      "tags": ["gta"], "containsSyntheticMedia": False},
         "transformation_note": " ".join(["word"] * 30),
         "commentary": {"path": None, "mic_source": "stream:1", "speech_seconds_live": 14.0,
                        "speech_seconds_combined": 14.0, "tts_used": False},
         "render": {"audio_mode": "mic_stem", "mic_source": "stream:1", "mic_gain": 1.0, "captions": "OFF"},
         "technical_qa": {"status": "PASS_TECHNICAL_ONLY"}, "paid_promotion": {"value": "none"}}
    c.update(over)
    return compliance.init_clip(c)


class Signals(unittest.TestCase):
    def test_audio_and_chat_move_the_pick_and_notes_explain(self):
        motion = [(float(t), 1.0) for t in range(0, 120, 2)]
        audio = [(float(t), -40.0 + (30 if 70 <= t < 80 else 0)) for t in range(120)]
        chat = [72.0 + i * 0.1 for i in range(50)]
        rows = signals.score_windows(120, motion, audio=audio, chat=chat, seconds=30)
        best = signals.select(rows, limit=1)[0]
        self.assertTrue(best["start"] <= 70 < best["end"])
        self.assertIn("audio", best["signals_used"])
        self.assertIn("chat", best["selection_note"] + str(best["signals_used"]))
        self.assertIn("human must confirm", best["selection_note"])

    def test_select_no_overlap_and_threshold(self):
        motion = [(float(t), float(t % 17)) for t in range(0, 300, 2)]
        picks = signals.select(signals.score_windows(300, motion, seconds=35), limit=8)
        for a in picks:
            for b in picks:
                if a is not b:
                    self.assertTrue(a["end"] <= b["start"] or a["start"] >= b["end"])
        self.assertEqual(signals.select(signals.score_windows(300, motion), min_score=101), [])

    def test_chat_formats(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "c.json"
            p.write_text(json.dumps({"comments": [{"content_offset_seconds": 5}, {"content_offset_seconds": 2}]}))
            self.assertEqual(signals.chat_times(p), [2.0, 5.0])


class Layouts(unittest.TestCase):
    def test_filters(self):
        self.assertIn("pad=1080:1920", render.video_filter("pad"))
        self.assertIn("boxblur", render.video_filter("blur"))
        self.assertIn("crop=1080:1920:(iw-1080)*0.2500", render.video_filter("crop", 0.25))
        self.assertIn("vstack", render.video_filter("split", 0.5, render.parse_box("0.7,0.0,0.3,0.3")))
        with self.assertRaises(ValueError):
            render.video_filter("split")
        with self.assertRaises(ValueError):
            render.parse_box("0.9,0,0.3,0.3")

    def test_loudnorm_always_and_no_shell_injection(self):
        cmd = render.build_command("in; rm -rf /.mp4", 1, 21, "short_01.mp4", layout="blur")
        self.assertIn("in; rm -rf /.mp4", cmd)  # passed as one argv item, never through a shell
        self.assertIn("loudnorm=I=-14", " ".join(cmd))
        with self.assertRaises(ValueError):
            render.build_command("v.mp4", 0, 20, "o.mp4", srt_name="x';evil.srt")


OWNER = {"CUTSCENECITY_OWNER_TWITCH_LOGIN": "cutscenecity", "CUTSCENECITY_OWNER_TWITCH_ID": ""}
SCRIPT = ("Okay so this is the part where I thought the cops gave up. They absolutely did not. Watch the left lane, "
          "I clip the bus, spin twice, and somehow the car still drives. Honestly that recovery was pure luck. "
          "Tell me if you would have bailed out there.")


def tts_clip(**over):
    c = good_clip(**over)
    c["commentary"].update({"tts_used": True, "voice_preset": "charon-relaxed", "path": "/v.wav", "speech_seconds_combined": 16.0})
    c["metadata"]["containsSyntheticMedia"] = True
    return c


class Gates(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, OWNER)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_everything_blocks_by_default(self):
        c = compliance.init_clip({"file": "a.mp4", "start": 0, "end": 20})
        b = compliance.blockers(c)
        for name in ("creator_owned_source", "vod_rights_confirmed", "no_story_cutscene", "music_risk_cleared",
                     "original_commentary", "live_reaction_preserved", "attribution", "transformation_note",
                     "metadata_spoiler_free", "technical_qa",
                     "overlays_third_parties_cleared", "paid_promotion_declared"):
            self.assertIn(name, b)
        self.assertNotIn("synthetic_disclosure", b)  # auto-answered (phase 2.3)
        self.assertIs(c["metadata"]["containsSyntheticMedia"], False)
        self.assertIn("no TTS", c["synthetic_disclosure_reason"])

    def test_good_clip_only_waits_for_humans(self):
        self.assertEqual(set(compliance.blockers(good_clip())), {"vod_rights_confirmed", "no_story_cutscene", "music_risk_cleared", "overlays_third_parties_cleared"})

    def test_human_signoff_rules(self):
        c = good_clip(provenance={})
        with self.assertRaises(PermissionError):
            compliance.signoff(c, "vod_rights_confirmed", "Shebin")
        c = good_clip(cutscene_scan={"letterbox_ratio": 0.8})
        with self.assertRaises(PermissionError):
            compliance.signoff(c, "no_story_cutscene", "Shebin", "ok")
        compliance.signoff(c, "no_story_cutscene", "Shebin", "letterbox is the in-game phone camera, gameplay")
        with self.assertRaises(ValueError):
            compliance.signoff(c, "original_commentary", "Shebin")

    def test_spoilers_attribution(self):
        c = good_clip()
        c["metadata"]["title"] = "GTA 6 ENDING explained"
        self.assertEqual(compliance.spoiler_gate(c, {})[0], "FAIL")
        c = good_clip()
        c["metadata"]["description"] = "no credit"
        self.assertEqual(compliance.attribution_gate(c, {})[0], "FAIL")

    def test_register_new_check_defaults_to_blocking(self):
        compliance.load_extra_checks({"extra_human_checks": [{"name": "content_id_cleared", "description": "x"}]})
        try:
            self.assertIn("content_id_cleared", compliance.blockers(good_clip()))
        finally:
            compliance.CHECKS.pop("content_id_cleared", None)


class CreatorOwned(unittest.TestCase):
    META = {"vod_id": "1234567890", "uploader": "CutsceneCity", "uploader_id": "cutscenecity", "channel": None, "channel_id": None}

    def test_owner_not_configured_fails_closed(self):
        self.assertEqual(compliance.owner_match(self.META, {}, "")[0], "FAIL")
        self.assertIn("not configured", compliance.owner_match(self.META, {"CUTSCENECITY_OWNER_TWITCH_LOGIN": " "}, "")[1])

    def test_policy_default_owner_is_cutscenecity(self):
        self.assertEqual(compliance.policy_owner_login(), "cutscenecity")
        ok = {"uploader": "CutsceneCity", "uploader_id": "cutscenecity"}
        self.assertEqual(compliance.owner_match(ok, {})[0], "PASS")  # env unset -> policy default
        for other in ("ishowspeed", "cutscenecity_fan", "xqc"):
            self.assertEqual(compliance.owner_match({"uploader": other, "uploader_id": other}, {})[0], "FAIL", other)
        self.assertEqual(compliance.owner_match(ok, {"CUTSCENECITY_OWNER_TWITCH_LOGIN": "someoneelse"})[0], "FAIL")  # env overrides
        clip = good_clip()
        self.assertEqual(compliance.creator_owned_source(clip, {"env": {}, "policy": {"owner_twitch_login": "cutscenecity"}})[0], "PASS")
        self.assertEqual(compliance.creator_owned_source(clip, {"env": {}, "policy": {}})[0], "FAIL")  # both empty: fail closed

    def test_unknown_channel_fails_closed(self):
        self.assertEqual(compliance.owner_match({}, OWNER)[0], "FAIL")
        self.assertEqual(compliance.owner_match({"uploader": "CutsceneCity"}, OWNER)[0], "FAIL")  # display name alone is not proof

    def test_match_and_mismatch(self):
        self.assertEqual(compliance.owner_match(self.META, OWNER)[0], "PASS")
        self.assertEqual(compliance.owner_match({**self.META, "uploader_id": "ishowspeed"}, OWNER)[0], "FAIL")
        self.assertEqual(compliance.owner_match({**self.META, "uploader_id": None, "channel": "kaicenat"}, OWNER)[0], "FAIL")
        self.assertEqual(compliance.owner_match({**self.META, "uploader_id": "CutsceneCity"}, OWNER)[0], "PASS")  # case-insensitive

    def test_numeric_id(self):
        env = {"CUTSCENECITY_OWNER_TWITCH_ID": "555"}
        self.assertEqual(compliance.owner_match({"channel_id": "555"}, env, "")[0], "PASS")
        self.assertEqual(compliance.owner_match({"channel_id": "556"}, env, "")[0], "FAIL")
        self.assertEqual(compliance.owner_match(self.META, env, "")[0], "FAIL")  # id configured but not reported
        both = {**OWNER, "CUTSCENECITY_OWNER_TWITCH_ID": "555"}
        self.assertEqual(compliance.owner_match({**self.META, "channel_id": "999"}, both)[0], "FAIL")

    def test_gate_checks_vod_id_and_no_licence_path(self):
        c = good_clip()
        self.assertEqual(compliance.creator_owned_source(c, {"env": OWNER})[0], "PASS")
        c["provenance"]["source_owner"]["vod_id"] = "999"
        self.assertEqual(compliance.creator_owned_source(c, {"env": OWNER})[0], "FAIL")
        c = good_clip()
        c["provenance"]["source_owner"]["uploader_id"] = "ishowspeed"
        c["provenance"]["licence"] = {"type": "written_permission", "reference": "x", "granted_by": "y", "expires": "2099-01-01"}
        self.assertEqual(compliance.creator_owned_source(c, {"env": OWNER})[0], "FAIL")
        self.assertFalse(hasattr(compliance, "provenance_licence"))
        self.assertNotIn("third_party_licences_enabled", (HERE / "editorial-policy.json").read_text())

    def test_pipeline_refuses_download_of_foreign_vod(self):
        import pipeline
        foreign = {"id": "v1234567890", "uploader": "IShowSpeed", "uploader_id": "ishowspeed"}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, OWNER), \
                mock.patch.object(pipeline, "fetch_info", return_value=foreign), mock.patch.object(pipeline, "run") as run, \
                mock.patch.object(sys, "argv", ["pipeline.py", "--url", "https://www.twitch.tv/videos/1234567890", "--output", d]):
            with self.assertRaises(PermissionError):
                pipeline.main()
            run.assert_not_called()  # nothing downloaded

    def test_set_cannot_change_provenance(self):
        self.assertNotIn("provenance", review.SETTABLE)


class CommentaryV3(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, OWNER)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_tts_counts_by_default_and_forces_synthetic(self):
        c = good_clip()
        c["commentary"].update({"speech_seconds_live": 6.0, "speech_seconds_combined": 14.0, "tts_used": True})
        c["metadata"]["containsSyntheticMedia"] = False
        self.assertEqual(compliance.commentary_gate(c, {})[0], "FAIL")      # (e) flag required
        self.assertEqual(compliance.disclosure_gate(c, {})[0], "FAIL")
        c["metadata"]["containsSyntheticMedia"] = True
        self.assertEqual(compliance.commentary_gate(c, {})[0], "PASS")      # live 6 s + TTS = 70%
        off = {"env": {"CUTSCENECITY_TTS_COUNTS_AS_COMMENTARY": "false"}}
        self.assertEqual(compliance.commentary_gate(c, off)[0], "FAIL")     # live only = 30%

    def test_live_reaction_never_muted_or_ducked(self):
        self.assertEqual(compliance.live_reaction_gate(good_clip(), {})[0], "PASS")
        no_mic = good_clip(render={"audio_mode": "source", "captions": "OFF"})
        self.assertIn("Twitch VODs have one mixed track", compliance.live_reaction_gate(no_mic, {})[1])
        self.assertEqual(compliance.music_hint(no_mic, {})[0], "FAIL")       # no fingerprint pre-check yet
        self.assertEqual(compliance.live_reaction_gate(good_clip(render={"audio_mode": "mic_stem", "mic_source": "x", "mic_gain": 0.3}), {})[0], "FAIL")
        for bad in ("mute", "duck"):
            with self.assertRaises(ValueError):
                render.audio_filter(bad, "1:a")
        with self.assertRaises(ValueError):
            render.build_command("v.mp4", 0, 20, "o.mp4", audio_mode="mic_stem")  # no mic: fail closed
        graph = " ".join(render.build_command("v.mp4", 0, 20, "o.mp4", audio_mode="mic_stem", mic_stream=1, commentary="t.wav"))
        self.assertIn("[0:a:1]volume=1.0", graph)
        self.assertIn("normalize=0", graph)
        self.assertNotIn("[0:a]", graph)                                     # opt-in strip: game/music mix dropped

    def test_script_required_when_tts_and_must_match_approval(self):
        c = tts_clip()
        self.assertEqual(compliance.script_gate(c, {})[0], "FAIL")
        c["commentary_script"] = {"text": SCRIPT, "approved_sha256": compliance._sha(SCRIPT), "approved_by": "Shebin"}
        self.assertEqual(compliance.script_gate(c, {})[0], "PASS")
        c["commentary_script"]["text"] = SCRIPT + " Edited later."
        self.assertEqual(compliance.script_gate(c, {})[0], "FAIL")
        self.assertEqual(compliance.script_gate(good_clip(), {})[0], "PASS")  # no TTS: optional

    def test_similarity_flag_reject_and_opener_cta(self):
        import script_checks
        other = {"clip_key": "other", "script": SCRIPT}
        self.assertEqual(script_checks.check_script(SCRIPT, [other], "me")[0], "FAIL")
        fresh = ("Right, new plan: I am stealing a garbage truck. It is slow, it is loud, and it is perfect for this. "
                 "The police helicopter has no idea what is coming next. I promise this ends badly for everyone. "
                 "Drop your best getaway vehicle below.")
        self.assertEqual(script_checks.check_script(fresh, [other], "me")[0], "PASS")
        same_opener = "Okay so this is the part where I thought the cops gave up. " + fresh
        st, why, _ = script_checks.check_script(same_opener, [other], "me")
        self.assertEqual(st, "FAIL")
        self.assertIn("opener", why)
        same_cta = fresh.rsplit(".", 2)[0] + ". Tell me if you would have bailed out there."
        self.assertIn("CTA", script_checks.check_script(same_cta, [other], "me")[1])
        self.assertEqual(script_checks.check_script(SCRIPT, [{"clip_key": "me", "script": SCRIPT}], "me")[0], "PASS")  # own clip ignored

    def test_warn_band_needs_reviewer_note(self):
        import script_checks
        a = " ".join(f"w{i}" for i in range(40))
        b = " ".join(f"w{i}" for i in range(22)) + " q1 q2 q3 q4"
        st, _, sim = script_checks.check_script(b, [{"clip_key": "o", "script": a}], "me")
        self.assertAlmostEqual(sim, 20 / 42, places=3)
        self.assertEqual(st, "WARN")
        b_hi = " ".join(f"w{i}" for i in range(30)) + " q1"
        self.assertEqual(script_checks.check_script(b_hi, [{"clip_key": "o", "script": a}], "me")[0], "FAIL")
        c = tts_clip(commentary_script={"text": b, "approved_sha256": compliance._sha(b)})
        hist = {"script_history": [{"clip_key": "o", "script": a}]}
        self.assertEqual(compliance.script_originality_gate(c, hist)[0], "FAIL")
        c["commentary_script"]["similarity_note"] = "same chase but the commentary angle is new"
        self.assertEqual(compliance.script_originality_gate(c, hist)[0], "PASS")

    def test_rotation(self):
        pol = json.loads((HERE / "editorial-policy.json").read_text())
        c = tts_clip()
        c["render"].update({"captions": "BURNED_IN_NEEDS_HUMAN_CHECK", "caption_style": "bold-white"})
        self.assertEqual(compliance.rotation_gate(c, {"policy": pol, "previous_upload": None})[0], "PASS")
        prev = {"voice_preset": "charon-relaxed", "caption_style": "yellow-pop"}
        self.assertIn("voice preset charon-relaxed repeats", compliance.rotation_gate(c, {"policy": pol, "previous_upload": prev})[1])
        prev = {"voice_preset": "puck-hyped", "caption_style": "bold-white"}
        self.assertIn("caption style bold-white repeats", compliance.rotation_gate(c, {"policy": pol, "previous_upload": prev})[1])
        c["commentary"]["voice_preset"] = "not-a-preset"
        self.assertEqual(compliance.rotation_gate(c, {"policy": pol, "previous_upload": None})[0], "FAIL")


class GameAudioDefault(unittest.TestCase):
    def test_default_keeps_game_audio_unchanged(self):
        self.assertEqual(render.audio_filter("source"), f"[0:a]volume=1.0,{render.LOUDNORM}[a]")
        mix = render.audio_filter("mix", "0:a:1", "1:a")
        self.assertIn("[0:a]volume=1.0[s]", mix)
        self.assertIn("[0:a:1]volume=1.0[m]", mix)
        self.assertIn("amix=inputs=3", mix)
        graph = " ".join(render.build_command("v.mp4", 0, 20, "o.mp4", audio_mode="mix", mic_stream=1, commentary="t.wav"))
        self.assertIn("[0:a:0]volume=1.0[s]", graph)
        for banned in ("highpass", "lowpass", "sidechaincompress", "volume=0[", "pan="):
            self.assertNotIn(banned, graph)
        self.assertNotIn("[0:a:0]", " ".join(render.build_command("v.mp4", 0, 20, "o.mp4", audio_mode="mic_stem", mic_stream=1)))

    def test_music_volume_setting(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CUTSCENECITY_MUSIC_VOLUME", None)
            self.assertEqual(render.music_volume(), 1.0)
        with mock.patch.dict(os.environ, {"CUTSCENECITY_MUSIC_VOLUME": "0.35"}):
            self.assertEqual(render.music_volume(), 0.35)
        self.assertEqual(render.music_volume(0.5), 0.5)
        for bad in (0, -1, 1.5):
            with self.assertRaises(ValueError):
                render.music_volume(bad)
        self.assertIn("[0:a]volume=0.35[s]", render.audio_filter("mix", "1:a", None, game_volume=0.35))

    def test_gates_not_loosened_for_kept_audio(self):
        kept = {"audio_mode": "mix", "mic_source": "stream:1", "mic_gain": 1.0, "music_volume": 1.0, "captions": "OFF"}
        self.assertEqual(compliance.live_reaction_gate(good_clip(render=kept), {})[0], "PASS")
        self.assertEqual(compliance.live_reaction_gate(good_clip(render={**kept, "mic_source": None}), {})[0], "FAIL")
        self.assertEqual(compliance.music_hint(good_clip(render=kept), {})[0], "FAIL")  # fingerprint still required
        c = good_clip(render=kept, fingerprint_precheck={"status": "NOT_INSTALLED"})
        self.assertEqual(compliance.music_hint(c, {})[0], "WARN")
        self.assertIn("Content ID", compliance.music_hint(c, {})[1])
        with self.assertRaises(PermissionError):
            compliance.signoff(c, "music_risk_cleared", "Shebin", "ok")  # note required
        self.assertEqual(compliance.cutscene_hint(good_clip(cutscene_scan={"letterbox_ratio": 0.9}), {})[0], "WARN")


class Profiles(unittest.TestCase):
    def test_blur_regions_from_profile(self):
        import pipeline
        prof = pipeline.layout_profile("facecam-right-chat-left")
        f = render.video_filter("blur", blur_regions=prof["blur_regions"])
        self.assertIn("boxblur=25:3", f)
        self.assertIn("crop=iw*0.22:ih*0.6:iw*0.0:ih*0.25", f)
        self.assertEqual(render.video_filter("pad"), render.video_filter("pad", blur_regions=[]))
        with self.assertRaises(ValueError):
            pipeline.layout_profile("nope")
        with self.assertRaises(ValueError):
            render.blur_chain([[0.9, 0.9, 0.5, 0.5]])

    def test_caption_style_injection_rejected(self):
        with self.assertRaises(ValueError):
            render.build_command("v.mp4", 0, 20, "o.mp4", srt_name="a.srt", caption_style="x'];[evil")


class SignedLog(unittest.TestCase):
    def test_chain_and_tamper(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CUTSCENECITY_REVIEW_KEY": KEY}):
            log = pathlib.Path(d) / "log.jsonl"
            gatelog.append_review(log, action="signoff", by="Shebin", clip="a")
            gatelog.append_review(log, action="approve", by="Shebin", clip="a")
            self.assertEqual(len(gatelog.verify_review_log(log)), 2)
            log.write_text(log.read_text().replace("Shebin", "Someone", 1))
            with self.assertRaises(PermissionError):
                gatelog.verify_review_log(log)
        with mock.patch.dict(os.environ, {"CUTSCENECITY_REVIEW_KEY": "short"}):
            with self.assertRaises(PermissionError):
                gatelog.append_review(pathlib.Path(d) / "x", action="a")


class FakeYouTube:
    def __init__(self, privacy="private", fail=False):
        self.privacy, self.fail, self.bodies = privacy, fail, []

    def videos(self):
        return self

    def insert(self, part, body, media_body):
        self.bodies.append(body)
        self.parts = getattr(self, "parts", []) + [part]
        return self

    def next_chunk(self):
        if self.fail:
            raise TimeoutError()
        return None, {"id": "VID123", "status": {"privacyStatus": self.privacy}}


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.vod = pathlib.Path(cls.tmp.name) / "src.mp4"
        make_vod(cls.vod)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.d = pathlib.Path(tempfile.mkdtemp(dir=self.tmp.name))
        self.root = self.d / "output"
        self.root.mkdir()
        shutil.copy(self.vod, self.root / "vod.mp4")
        (self.d / "vod.info.json").write_text(json.dumps({"id": "v1234567890", "uploader": "CutsceneCity", "uploader_id": "cutscenecity"}))
        self.env = mock.patch.dict(os.environ, {"CUTSCENECITY_REVIEW_KEY": KEY, **OWNER,
                                                "CUTSCENECITY_STATE_DIR": str(self.d / "state"), "CUTSCENECITY_DAILY_CAP": "5"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def pipeline(self, *extra):
        subprocess.run([sys.executable, str(HERE / "pipeline.py"), "--input", str(self.root / "vod.mp4"), "--output",
                        str(self.root), "--seconds", "20", "--limit", "1", "--render", "--info-json", str(self.d / "vod.info.json"), *extra], check=True)
        return json.loads((self.root / "manifest.json").read_text())

    def rv(self, *args):
        review.main([args[0], "--output", str(self.root), "--clip", "short_01.mp4", *args[1:]])

    def approved_package(self, tts=True, paid="none"):
        m = self.pipeline("--layout", "split", "--facecam-box", "0.7,0,0.3,0.3")
        clip = m["clips"][0]
        self.assertIn("selection_note", clip)
        self.assertEqual(clip["provenance"]["source_owner"]["uploader_id"], "cutscenecity")
        self.assertEqual(clip["compliance"]["creator_owned_source"]["status"], "PASS")
        self.assertTrue(clip["start"] <= 40 < clip["end"] or clip["start"] < 46 <= clip["end"], clip)  # loud burst found
        details = self.d / "details.json"
        details.write_text(json.dumps({k: v for k, v in good_clip().items() if k in ("metadata", "transformation_note")}))
        self.rv("set", "--file", str(details), "--by", "Shebin")
        voice = self.d / "voice.wav"
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=200:duration=20", str(voice))
        with self.assertRaises(SystemExit):  # no separate mic: fail closed
            self.rv("commentary", "--audio", str(voice))
        if tts:
            self.rv("commentary", "--audio", str(voice), "--mic-stream", "1", "--tts", "--voice-preset", "charon-relaxed")
            script = self.d / "script.txt"
            script.write_text(SCRIPT)
            self.rv("script", "--file", str(script), "--by", "Shebin")
        else:
            self.rv("commentary", "--mic-stream", "1")
        with self.assertRaises(SystemExit):  # overlay check needs a scan of this exact render
            self.rv("signoff", "--check", "overlays_third_parties_cleared", "--by", "Shebin", "--note", "chat column blurred, no guests")
        self.rv("precheck")
        scan = json.loads((self.root / "manifest.json").read_text())["clips"][0]["overlay_scan"]
        self.assertIn("edge-density", scan["methods"])
        with self.assertRaises(SystemExit):
            self.rv("approve", "--by", "Shebin")
        for check in ("vod_rights_confirmed", "no_story_cutscene", "music_risk_cleared", "overlays_third_parties_cleared"):
            self.rv("signoff", "--check", check, "--by", "Shebin", "--note", "watched the full clip twice, gameplay only")
        with self.assertRaises(SystemExit) as cm:  # paid_promotion missing blocks
            self.rv("approve", "--by", "Shebin")
        self.assertIn("paid_promotion", str(cm.exception))
        with self.assertRaises(SystemExit):
            self.rv("paid", "--value", "maybe", "--by", "Shebin")
        self.rv("paid", "--value", paid, "--by", "Shebin")
        self.rv("approve", "--by", "Shebin")
        self.rv("export", "--packages", str(self.d / "packages"))
        return next((self.d / "packages").iterdir())

    def test_full_review_then_private_upload_mocked(self):
        pkg_dir = self.approved_package()
        pkg = json.loads((pkg_dir / "package.json").read_text())
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json", str(pkg_dir / "video.mp4")],
                             capture_output=True, text=True)
        self.assertIn('"width": 1080', out.stdout)
        _, problems = upload_private.verify_package(pkg_dir)
        self.assertEqual(problems, [])
        with self.assertRaises(PermissionError):
            upload_private.upload(pkg_dir, "wrong", youtube=FakeYouTube(), media_factory=lambda p: p)
        yt = FakeYouTube()
        self.assertEqual(upload_private.upload(pkg_dir, pkg["package_sha256"][:12], youtube=yt, media_factory=lambda p: p), "VID123")
        status = yt.bodies[0]["status"]
        self.assertEqual(status["privacyStatus"], "private")
        self.assertIs(status["selfDeclaredMadeForKids"], False)
        self.assertNotIn("publishAt", status)
        self.assertIs(status["containsSyntheticMedia"], True)  # TTS used -> forced
        self.assertEqual(yt.bodies[0]["paidProductPlacementDetails"], {"hasPaidProductPlacement": False})
        self.assertIn("paidProductPlacementDetails", yt.parts[0])
        self.assertIsInstance(pkg["source"]["start_ms"], int)
        imp = json.loads((pkg_dir / "agent-import.json").read_text())
        self.assertEqual((imp["privacyStatus"], imp["selfDeclaredMadeForKids"]), ("private", False))
        ledger = gatelog.read_ledger()
        self.assertEqual([e["status"] for e in ledger], ["ATTEMPT", "UPLOADED"])
        with self.assertRaises(PermissionError):  # duplicate
            upload_private.upload(pkg_dir, pkg["package_sha256"][:12], youtube=FakeYouTube(), media_factory=lambda p: p)

    def test_tamper_timeout_cap_and_public_response(self):
        pkg_dir = self.approved_package()
        pkg = json.loads((pkg_dir / "package.json").read_text())
        code = pkg["package_sha256"][:12]
        with self.assertRaises(TimeoutError):
            upload_private.upload(pkg_dir, code, youtube=FakeYouTube(fail=True), media_factory=lambda p: p)
        _, problems = upload_private.verify_package(pkg_dir)
        self.assertTrue(any("already sent" in p or "reconcile" in p for p in problems))
        upload_private.reconcile(pkg_dir, "NONE", "Shebin")
        with mock.patch.dict(os.environ, {"CUTSCENECITY_DAILY_CAP": "1"}):
            self.assertTrue(any("daily cap" in p for p in upload_private.verify_package(pkg_dir)[1]))
        # next IST day: move today's ledger rows to yesterday so the cap frees up
        led = gatelog.ledger_path()
        rows = [json.loads(l) for l in led.read_text().splitlines()]
        for r in rows:
            r["at"] = "2000-01-01" + r["at"][10:]
        led.write_text("".join(json.dumps(r) + "\n" for r in rows))
        with self.assertRaises(RuntimeError):
            upload_private.upload(pkg_dir, code, youtube=FakeYouTube(privacy="public"), media_factory=lambda p: p)
        clip = json.loads((pkg_dir / "clip.json").read_text())
        clip["metadata"]["title"] = "Changed after approval"
        (pkg_dir / "clip.json").write_text(json.dumps(clip))
        self.assertTrue(upload_private.verify_package(pkg_dir)[1])

    def test_rerender_revokes_signoffs(self):
        self.approved_package()
        voice = self.d / "voice2.wav"
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=250:duration=20", str(voice))
        self.rv("commentary", "--audio", str(voice), "--mic-stream", "1", "--tts", "--voice-preset", "puck-hyped")
        m = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(m["clips"][0]["compliance"]["no_story_cutscene"]["status"], "PENDING")
        self.assertEqual(m["clips"][0]["compliance"]["overlays_third_parties_cleared"]["status"], "PENDING")
        self.assertNotIn("overlay_scan", m["clips"][0])
        self.assertNotIn("paid_promotion", m["clips"][0])
        with self.assertRaises(SystemExit):
            self.rv("export", "--packages", str(self.d / "p2"))


    def test_script_edit_after_approval_blocks_export(self):
        pkg_dir = self.approved_package()
        m = json.loads((self.root / "manifest.json").read_text())
        m["clips"][0]["commentary_script"]["text"] += " sneaky edit"
        (self.root / "manifest.json").write_text(json.dumps(m))
        with self.assertRaises(SystemExit):
            self.rv("export", "--packages", str(self.d / "p3"))
        self.assertTrue(pkg_dir.exists())

    def test_mixed_track_path_end_to_end(self):
        m = self.pipeline()
        clip = m["clips"][0]
        self.assertEqual(clip["technical_qa"]["status"], "PASS_TECHNICAL_ONLY")          # qa.py ran at --render
        self.assertEqual(clip["compliance"]["technical_qa"]["status"], "PASS")
        self.assertEqual(clip["metadata"]["description"],
                         "From my Twitch stream: https://www.twitch.tv/cutscenecity \u2014 full VOD: https://www.twitch.tv/videos/1234567890")
        self.assertEqual(clip["compliance"]["attribution"]["status"], "PASS")
        self.assertEqual(clip["compliance"]["synthetic_disclosure"]["status"], "PASS")
        self.assertIsInstance(clip["commentary"]["mixed_track_speech_share"], float)
        for g in ("original_commentary", "live_reaction_preserved"):
            self.assertEqual(clip["compliance"][g]["status"], "WARN", clip["compliance"][g])
        self.assertNotIn("paid_promotion", clip)                                          # suggestion only
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.rv("status")
        st = json.loads(buf.getvalue())
        self.assertIn("title", st["missing_creative_input"])
        self.assertIn("review.py paid --clip short_01.mp4 --value none", st["how_to_fix"]["paid_promotion_declared"])
        self.assertIn("NOT DECLARED", st["paid_promotion"])
        self.assertIn("mixed_track_commentary_confirmed", st["how_to_fix"])
        details = self.d / "details.json"
        md = dict(clip["metadata"], title="This getaway went sideways fast")
        details.write_text(json.dumps({"metadata": md, "transformation_note": " ".join(["word"] * 30)}))
        self.rv("set", "--file", str(details), "--by", "Shebin")
        self.rv("precheck")
        for check in ("vod_rights_confirmed", "no_story_cutscene", "music_risk_cleared", "overlays_third_parties_cleared"):
            self.rv("signoff", "--check", check, "--by", "Shebin", "--note", "watched the full clip twice, gameplay only")
        self.rv("paid", "--value", "none", "--by", "Shebin")
        with self.assertRaises(SystemExit):   # mixed track not yet confirmed
            self.rv("approve", "--by", "Shebin")
        with self.assertRaises(SystemExit):   # note too short
            self.rv("signoff", "--check", "mixed_track_commentary_confirmed", "--by", "Shebin", "--note", "audible")
        self.rv("signoff", "--check", "mixed_track_commentary_confirmed", "--by", "Shebin", "--note", "my live commentary is clearly audible throughout")
        self.rv("approve", "--by", "Shebin")
        self.rv("export", "--packages", str(self.d / "packages"))
        pkg_dir = next((self.d / "packages").iterdir())
        self.assertEqual(upload_private.verify_package(pkg_dir)[1], [])
        c2 = json.loads((pkg_dir / "clip.json").read_text())
        self.assertEqual(c2["commentary"]["commentary_source"], "mixed_track_signed")
        self.assertEqual(c2["compliance"]["original_commentary"]["status"], "PASS")
        c2["commentary"]["commentary_source"] = None
        (pkg_dir / "clip.json").write_text(json.dumps(c2))
        self.assertTrue(any("commentary_source" in p for p in upload_private.verify_package(pkg_dir)[1]))

    def test_live_voice_only_no_tts_no_script(self):
        pkg_dir = self.approved_package(tts=False)
        self.assertEqual(upload_private.verify_package(pkg_dir)[1], [])
        clip = json.loads((pkg_dir / "clip.json").read_text())
        self.assertIs(clip["metadata"]["containsSyntheticMedia"], False)
        self.assertEqual(clip["render"]["audio_mode"], "mix")  # default keeps original game audio
        self.assertEqual((clip["render"]["game_audio"], clip["render"]["music_volume"]), ("kept", 1.0))


    def test_paid_present_is_sent_true_and_tamper_blocks(self):
        pkg_dir = self.approved_package(paid="present")
        pkg = json.loads((pkg_dir / "package.json").read_text())
        self.assertIs(pkg["upload"]["paidProductPlacement"], True)
        self.assertEqual(upload_private.verify_package(pkg_dir)[1], [])
        clip = json.loads((pkg_dir / "clip.json").read_text())
        clip["paid_promotion"]["value"] = "none"
        (pkg_dir / "clip.json").write_text(json.dumps(clip))
        self.assertTrue(any("paid_promotion" in p for p in upload_private.verify_package(pkg_dir)[1]))
        clip["paid_promotion"]["value"] = "present"
        clip["overlay_scan"]["file_sha256"] = "0" * 64
        (pkg_dir / "clip.json").write_text(json.dumps(clip))
        self.assertTrue(any("overlay scan" in p for p in upload_private.verify_package(pkg_dir)[1]))
        clip["overlay_scan"]["file_sha256"] = pkg["file_sha256"]
        (pkg_dir / "clip.json").write_text(json.dumps(clip))
        yt = FakeYouTube()
        upload_private.upload(pkg_dir, pkg["package_sha256"][:12], youtube=yt, media_factory=lambda p: p)
        self.assertEqual(yt.bodies[0]["paidProductPlacementDetails"], {"hasPaidProductPlacement": True})

    def test_env_cap_cannot_exceed_two(self):
        pkg_dir = self.approved_package()  # setUp sets CUTSCENECITY_DAILY_CAP=5
        pkg = json.loads((pkg_dir / "package.json").read_text())
        gatelog.audit(status="ATTEMPT", package_sha256="x" * 64, file_sha256="y" * 64, vod_id="999", start_ms=0, end_ms=1)
        self.assertFalse(any("daily cap" in p for p in upload_private.verify_package(pkg_dir)[1]))  # 1 of 2 used: still allowed
        gatelog.audit(status="ATTEMPT", package_sha256="z" * 64, file_sha256="w" * 64, vod_id="998", start_ms=0, end_ms=1)
        problems = upload_private.verify_package(pkg_dir)[1]
        self.assertTrue(any("daily cap reached: 2/2" in p for p in problems), problems)  # 3rd upload today blocked
        self.assertEqual(pkg["upload"]["paidProductPlacement"], False)


class DailyCap(unittest.TestCase):
    def test_clamp_and_fail_closed(self):
        cap = gatelog.effective_daily_cap
        self.assertEqual(gatelog.HARD_DAILY_CAP, 2)
        self.assertEqual(cap("5", 1), 2)
        self.assertEqual(cap("2", 1), 2)
        self.assertEqual(cap(None, 2), 2)
        self.assertEqual(cap(None, 10), 2)
        self.assertEqual(cap("", 3), 2)
        self.assertEqual(cap("1", None), 1)
        self.assertEqual(cap("1", 2), 1)
        self.assertEqual(cap("0", 1), 0)
        self.assertEqual(cap("-3", 1), 0)
        self.assertEqual(cap("abc", 1), 0)
        self.assertEqual(cap("1.5", 1), 0)
        self.assertEqual(cap(None, 0), 0)
        self.assertEqual(cap(None, True), 0)
        self.assertEqual(cap(None, None), 2)
        self.assertEqual(cap(None, ""), 0)

    def test_zero_cap_blocks_upload(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CUTSCENECITY_STATE_DIR": d}):
            pkg = {"package_sha256": "a" * 64, "file_sha256": "b" * 64, "source": {"vod_id": "1", "start_ms": 0, "end_ms": 10}}
            self.assertTrue(any("disabled" in p for p in gatelog.upload_blockers(pkg, 0)))
            self.assertTrue(any("disabled" in p for p in gatelog.upload_blockers(pkg, -1)))
            self.assertEqual(gatelog.upload_blockers(pkg, 1), [])
            gatelog.audit(status="ATTEMPT", package_sha256="c" * 64, file_sha256="d" * 64, vod_id="2", start_ms=0, end_ms=1)
            self.assertTrue(any("1/1" in p for p in gatelog.upload_blockers(pkg, 1)))
            self.assertEqual(gatelog.upload_blockers(pkg, 2), [])        # 2nd upload today allowed
            self.assertEqual(gatelog.upload_blockers(pkg, 7), [])        # 7 clamps to 2
            gatelog.audit(status="ATTEMPT", package_sha256="e" * 64, file_sha256="f" * 64, vod_id="3", start_ms=0, end_ms=1)
            self.assertTrue(any("2/2" in p for p in gatelog.upload_blockers(pkg, 7)))   # 3rd blocked
            self.assertTrue(any("2/2" in p for p in gatelog.upload_blockers(pkg, 2)))

    def test_day_boundary_is_ist(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CUTSCENECITY_STATE_DIR": d}):
            pkg = {"package_sha256": "a" * 64, "file_sha256": "b" * 64, "source": {"vod_id": "1", "start_ms": 0, "end_ms": 10}}
            for i in range(2):
                gatelog.audit(status="ATTEMPT", package_sha256=str(i) * 64, file_sha256=str(i + 2) * 64, vod_id=f"9{i}", start_ms=0, end_ms=1)
            row = json.loads(gatelog.ledger_path().read_text().splitlines()[0])
            self.assertTrue(row["at"].endswith("+05:30"), row["at"])
            today = row["at"][:10]
            self.assertTrue(any("2/2" in p for p in gatelog.upload_blockers(pkg, 2, today=today)))
            self.assertEqual(gatelog.upload_blockers(pkg, 2, today="2099-01-01"), [])   # next IST day frees up


class PaidPromotion(unittest.TestCase):
    def test_missing_blocks_and_body_explicit(self):
        self.assertEqual(compliance.paid_gate(good_clip(paid_promotion=None), {})[0], "FAIL")
        self.assertEqual(compliance.paid_gate(good_clip(paid_promotion={"value": "maybe"}), {})[0], "FAIL")
        self.assertEqual(compliance.paid_gate(good_clip(), {})[0], "PASS")
        up = {"title": "t", "description": "d", "containsSyntheticMedia": False, "privacyStatus": "private"}
        with self.assertRaises(PermissionError):
            upload_private.build_body({"upload": up})
        for v in (False, True):
            body = upload_private.build_body({"upload": {**up, "paidProductPlacement": v}})
            self.assertIs(body["paidProductPlacementDetails"]["hasPaidProductPlacement"], v)
        self.assertEqual(upload_private.PART, "snippet,status,paidProductPlacementDetails")


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
class OverlayScan(unittest.TestCase):
    def video(self, d, name, vf):
        out = pathlib.Path(d) / name
        ffmpeg("-f", "lavfi", "-i", "nullsrc=s=270x480:r=10:d=3,geq=lum='random(1)*255':cb=128:cr=128",
               "-vf", vf, "-pix_fmt", "yuv420p", str(out))
        return out

    def test_static_text_box_flagged_moving_and_blurred_not(self):
        import overlay_scan
        no_tess = lambda _: None  # noqa: E731
        box = "drawbox=x=0:y=0:w=270:h=480:c=gray:t=fill,drawgrid=x=10:y=150:w=6:h=4:t=1:c=white"
        with tempfile.TemporaryDirectory() as d:
            moving = overlay_scan.scan(self.video(d, "m.mp4", "null"), "s", which=no_tess)
            self.assertEqual(moving["methods"], ["edge-density"])
            self.assertIs(moving["flagged"], False, moving)
            chat = "drawbox=x=0:y=96:w=90:h=192:c=gray:t=fill,drawgrid=w=6:h=4:t=1:c=white"
            static = overlay_scan.scan(self.video(d, "s.mp4", chat), "s", which=no_tess)
            self.assertIs(static["flagged"], True)
            self.assertTrue(all(c[0] < 0.34 and 0.19 <= c[1] < 0.6 for c in static["edge_cells"]), static["edge_cells"])
            calm = overlay_scan.scan(self.video(d, "b.mp4", box + ",boxblur=20:3"), "s", which=no_tess)
            self.assertIs(calm["flagged"], False, calm)

    def test_tesseract_path_mocked_and_text_never_stored(self):
        import overlay_scan
        tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
               + "".join(f"5\t1\t1\t1\t1\t{i}\t{10 * i}\t20\t30\t10\t91\tviewer{i}\n" for i in range(4)))
        run = mock.Mock(return_value=mock.Mock(returncode=0, stdout=tsv))
        with tempfile.TemporaryDirectory() as d:
            r = overlay_scan.scan(self.video(d, "m.mp4", "null"), "s", which=lambda _: "/usr/bin/tesseract", run=run)
        self.assertIn("tesseract", r["methods"])
        self.assertTrue(r["flagged"])
        self.assertNotIn("viewer", json.dumps(r))

    def test_hint_states(self):
        self.assertEqual(compliance.overlay_hint(good_clip(), {})[0], "FAIL")
        self.assertEqual(compliance.overlay_hint(good_clip(overlay_scan={"flagged": None}), {})[0], "WARN")
        self.assertEqual(compliance.overlay_hint(good_clip(overlay_scan={"flagged": True, "regions": [[0, 0, 1, 1]], "methods": ["edge-density"]}), {})[0], "WARN")
        self.assertEqual(compliance.overlay_hint(good_clip(overlay_scan={"flagged": False}), {})[0], "PASS")
        c = good_clip(overlay_scan={"flagged": True, "regions": [], "methods": []})
        with self.assertRaises(PermissionError):
            compliance.signoff(c, "overlays_third_parties_cleared", "Shebin", "ok")
        compliance.signoff(c, "overlays_third_parties_cleared", "Shebin", "chat blurred, alerts off, no guests")


def mixed_clip(**over):
    c = good_clip(commentary={"mic_source": None, "tts_used": False, "mixed_track_speech_share": 0.71},
                  render={"audio_mode": "source", "mic_source": None, "music_volume": 1.0, "captions": "OFF"})
    c.update(over)
    return compliance.init_clip(c)


class MixedTrack(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, OWNER)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_owner_mixed_track_warns_until_signed(self):
        c = mixed_clip()
        b = compliance.blockers(c)
        self.assertEqual(c["compliance"]["original_commentary"]["status"], "WARN")
        self.assertEqual(c["compliance"]["live_reaction_preserved"]["status"], "WARN")
        self.assertIn("71%", c["compliance"]["original_commentary"]["evidence"])          # hint shown
        self.assertIn("mixed_track_commentary_confirmed", b)
        self.assertIn("mixed_track_commentary_confirmed", compliance.required_human_checks(c))
        with self.assertRaises(PermissionError):
            compliance.signoff(c, "mixed_track_commentary_confirmed", "Shebin", "fine")       # 5+ words
        compliance.signoff(c, "mixed_track_commentary_confirmed", "Shebin", "my commentary is audible over the game")
        compliance.evaluate(c)
        self.assertEqual(c["compliance"]["original_commentary"]["status"], "PASS")
        self.assertEqual(c["compliance"]["live_reaction_preserved"]["status"], "PASS")

    def test_hint_alone_never_passes(self):
        c = mixed_clip(commentary={"mic_source": None, "tts_used": False, "mixed_track_speech_share": 1.0})
        compliance.evaluate(c)
        self.assertEqual(c["compliance"]["original_commentary"]["status"], "WARN")

    def test_non_owner_stays_rejected(self):
        meta = {"vod_id": "1234567890", "uploader": "Other", "uploader_id": "otherstreamer"}
        c = mixed_clip()
        c["provenance"]["source_owner"] = meta
        compliance.evaluate(c)
        for g in ("original_commentary", "live_reaction_preserved", "creator_owned_source"):
            self.assertEqual(c["compliance"][g]["status"], "FAIL", g)
        with self.assertRaises(PermissionError):
            compliance.signoff(c, "mixed_track_commentary_confirmed", "Shebin", "my commentary is audible over the game")

    def test_mic_stem_preferred_and_mixed_check_not_applicable(self):
        c = good_clip()
        compliance.evaluate(c)
        self.assertTrue(c["compliance"]["mixed_track_commentary_confirmed"]["not_applicable"])
        self.assertNotIn("mixed_track_commentary_confirmed", compliance.required_human_checks(c))
        with self.assertRaises(ValueError):
            compliance.signoff(c, "mixed_track_commentary_confirmed", "Shebin", "my commentary is audible over the game")
        thin = good_clip(commentary={"mic_source": "stream:1", "speech_seconds_live": 3.0, "speech_seconds_combined": 3.0, "tts_used": False})
        self.assertEqual(compliance.commentary_gate(thin, {})[0], "FAIL")                   # measured path stays strict

    def test_lowered_mixed_track_fails(self):
        c = mixed_clip(render={"audio_mode": "source", "mic_source": None, "music_volume": 0.5, "captions": "OFF"})
        self.assertEqual(compliance.live_reaction_gate(c, {})[0], "FAIL")


class AutoDefaults(unittest.TestCase):
    def test_disclosure_auto_and_never_flipped(self):
        c = good_clip(metadata={"title": "t", "containsSyntheticMedia": None})
        compliance.evaluate(c)
        self.assertIs(c["metadata"]["containsSyntheticMedia"], False)
        t = good_clip(metadata={"title": "t", "containsSyntheticMedia": None}, ai_visuals_used=True)
        compliance.evaluate(t)
        self.assertIs(t["metadata"]["containsSyntheticMedia"], True)
        self.assertIn("AI", t["synthetic_disclosure_reason"])
        bad = good_clip(ai_visuals_used=True)          # explicit False with AI use: still FAIL
        self.assertEqual(compliance.disclosure_gate(bad, {})[0], "FAIL")

    def test_credit_line_factual(self):
        import pipeline
        self.assertEqual(pipeline.credit_line({"uploader_id": "cutscenecity"}, "https://www.twitch.tv/videos/1"),
                         "From my Twitch stream: https://www.twitch.tv/cutscenecity \u2014 full VOD: https://www.twitch.tv/videos/1")
        self.assertEqual(pipeline.credit_line({}, "https://www.twitch.tv/videos/1"), "")

    def test_speech_hint_runs(self):
        if not HAS_FFMPEG:
            self.skipTest("ffmpeg")
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "a.wav"
            ffmpeg("-f", "lavfi", "-i", "sine=frequency=1000:duration=4", "-af", "volume='if(lt(t,2),1,0)':eval=frame", str(f))
            share = compliance.mixed_speech_share(f)
        self.assertTrue(0.3 < share < 0.7, share)


class Upscale(unittest.TestCase):
    def test_default_is_2160_and_off_opt_out(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CUTSCENECITY_UPSCALE", None)
            self.assertEqual(render.upscale_setting(), "2160")
        with mock.patch.dict(os.environ, {"CUTSCENECITY_UPSCALE": "off"}):
            self.assertIsNone(render.upscale_setting())
            self.assertEqual(render.upscale_setting("1440"), "1440")      # flag beats env
        self.assertIsNone(render.upscale_setting("off"))
        with self.assertRaises(ValueError):
            render.upscale_setting("4320")

    def test_command_shape(self):
        cmd = " ".join(render.upscale_command("in.mp4", "out.mp4", 2160, 3840))
        for part in ("scale=2160:3840:flags=lanczos", "unsharp=5:5:0.5", "-crf 18", "-pix_fmt yuv420p", "-c:a copy", "+faststart"):
            self.assertIn(part, cmd)

    @unittest.skipUnless(HAS_FFMPEG, "ffmpeg required")
    def test_upscale_real_file_audio_unchanged_and_qa_accepts(self):
        import qa
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "c.mp4"
            ffmpeg("-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=30:d=16", "-f", "lavfi", "-i", "sine=frequency=440:duration=16",
                   "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(f))
            amd5 = lambda p: subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:a", "-c", "copy", "-f", "md5", "-"],  # noqa: E731
                                            capture_output=True, text=True).stdout
            before = amd5(f)
            info = render.upscale(f, "1440")
            self.assertEqual(info["output_resolution"], "1440x2560")
            self.assertEqual(render.video_size(f), (1440, 2560))
            self.assertEqual(amd5(f), before)                                   # audio stream copied unchanged
            self.assertEqual(qa.validate(f, 0, 16)["status"], "PASS_TECHNICAL_ONLY")
            again = render.upscale(f, "1440")                                    # never re-upscale / above target
            self.assertTrue(again["upscale"].startswith("skipped"))
            self.assertTrue(render.upscale(f, "2160")["upscale"] == "2160")
            self.assertEqual(render.video_size(f), (2160, 3840))
            self.assertTrue(render.upscale(f, "1440")["upscale"].startswith("skipped"))   # source above target: skip


class Defaults(unittest.TestCase):
    def test_policy_defaults(self):
        pol = json.loads((HERE / "editorial-policy.json").read_text())
        self.assertEqual(pol["daily_upload_cap"], 2)
        self.assertEqual(pol["default_layout"], "blur")
        self.assertEqual(pol["source_policy"], "creator_owned_only")
        self.assertNotIn("source_vod", pol)

    def test_no_default_vod_anywhere(self):
        for path in [HERE.parents[1] / ".github/workflows/twitch-vod-shorts.yml", *HERE.glob("*.py"), *HERE.glob("*.md"), *HERE.glob("*.json")]:
            self.assertNotIn("29365" + "44559", path.read_text(), str(path))

    def test_pipeline_requires_explicit_source_and_defaults_to_blur(self):
        p = subprocess.run([sys.executable, str(HERE / "pipeline.py"), "--output", tempfile.mkdtemp()], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no default source", p.stderr)
        self.assertIn('default="blur"', (HERE / "pipeline.py").read_text())


class Revoke(unittest.TestCase):
    def test_revoke_calls_google_and_deletes_token(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"CUTSCENECITY_STATE_DIR": d}):
            (pathlib.Path(d) / "token.json").write_text(json.dumps({"refresh_token": "fake-refresh"}))
            seen = []
            self.assertEqual(upload_private.revoke(opener=lambda req, timeout: seen.append(req)), "revoked at Google")
            self.assertEqual(seen[0].full_url, "https://oauth2.googleapis.com/revoke")
            self.assertFalse((pathlib.Path(d) / "token.json").exists())


class Workflow(unittest.TestCase):
    def test_ci_never_uploads(self):
        text = (HERE.parents[1] / ".github/workflows/twitch-vod-shorts.yml").read_text()
        for banned in ("upload_private", "review.py approve", "YOUTUBE", "CLIENT_SECRET", "REVIEW_KEY", "youtube.upload"):
            self.assertNotIn(banned, text)


if __name__ == "__main__":
    unittest.main()
