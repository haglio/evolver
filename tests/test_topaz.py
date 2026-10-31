from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import pytest

import config
from util import orientation, topaz

_EXAMPLE = topaz.Settings(name="example", version="v000",
                        filter_complex="the-filter", videoai_tag="the-tag")


def _turned_to_an_example_video(settings: topaz.Settings, orient: str) -> topaz.Settings:
    """*settings* turned to a video written at 112 fps by a model generating at 16."""
    return topaz.framed(settings, orient, video_fps=Fraction(112), generated_fps=Fraction(16))


class TestCommand(unittest.TestCase):
    def test_builds_silent_video_command(self):
        cmd = topaz.command(Path("in.mp4"), Path("tmp.mp4"), _EXAMPLE)
        assert cmd[0] == str(config.FFMPEG)
        assert "in.mp4" in cmd
        assert "the-filter" in cmd
        assert "videoai=the-tag" in cmd
        assert "-an" in cmd
        assert cmd[-1] == "tmp.mp4"

    def test_keep_audio_reencodes_instead_of_stripping(self):
        cmd = topaz.command(Path("in.mp4"), Path("tmp.mp4"), replace(_EXAMPLE, keep_audio=True))
        assert "-an" not in cmd
        assert "aac" in cmd

    def test_all_settings_keep_the_soundtrack(self):
        for settings in topaz.ALL_SETTINGS:
            with self.subTest(settings=settings.name):
                runnable = _turned_to_an_example_video(settings, orientation.LANDSCAPE)
                assert "-an" not in topaz.command(Path("in.mp4"), Path("tmp.mp4"), runnable)

    def test_names_the_container_outright_since_the_file_it_writes_has_no_extension(self):
        cmd = topaz.command(Path("in.mp4"), Path("scene one.partial.ab12"), _EXAMPLE)
        assert cmd[cmd.index("-f") + 1] == "mp4"

    def test_settings_aimed_at_a_frame_are_refused_until_turned_to_the_video(self):
        """Unframed, its filter would reach Topaz still asking for {width}."""
        with pytest.raises(ValueError, match="non_ai_upscale still names"):
            topaz.command(Path("in.mp4"), Path("tmp.mp4"), topaz.NON_AI_UPSCALE)


# The chain chosen by comparing versions side by side, as the trial ran it on a
# video Origenerator generated at 16 fps and wrote at 112.
_THE_TRIALS_CHAIN = (
    "select='not(mod(n,7))',fps=16,"
    "tvai_up=model=rxl-1:scale=4:estimate=20:preblur=-0.4:noise=0:details=0.7:halo=0:blur=0.8:"
    "compression=0.8:blend=0:download=0:device=0:vram=1:instances=1,"
    "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:download=0:device=0:vram=1:instances=1"
)


def _frames_given_to_topaz(**rates) -> str:
    turned = topaz.framed(topaz.AI_UPSCALE_ORIGENERATOR, orientation.PORTRAIT, **rates)
    return turned.filter_complex[:turned.filter_complex.index(",tvai_up=")]


class TestTheOrigeneratorSettings(unittest.TestCase):
    def test_a_video_written_at_seven_times_its_generated_rate_runs_the_trials_chain(self):
        turned = topaz.framed(topaz.AI_UPSCALE_ORIGENERATOR, orientation.PORTRAIT,
                              video_fps=Fraction(112), generated_fps=Fraction(16))

        assert turned.filter_complex == _THE_TRIALS_CHAIN

    def test_a_video_written_at_no_whole_multiple_of_its_generated_rate_keeps_every_frame(self):
        assert _frames_given_to_topaz(video_fps=Fraction(24), generated_fps=Fraction(16)) == "select='not(mod(n,1))',fps=24"

    def test_a_video_whose_generated_rate_nothing_publishes_keeps_every_frame(self):
        assert _frames_given_to_topaz(video_fps=Fraction(112), generated_fps=None) == "select='not(mod(n,1))',fps=112"

    def test_a_video_whose_own_rate_cannot_be_read_keeps_every_frame_at_that_rate(self):
        assert _frames_given_to_topaz(video_fps=None, generated_fps=Fraction(16)) == "select='not(mod(n,1))',fps=source_fps"

    def test_is_refused_until_it_is_turned_to_the_video(self):
        """Unturned, its filter would reach Topaz still asking for {every}."""
        with pytest.raises(ValueError, match="ai_upscale_origenerator still names"):
            topaz.command(Path("in.mp4"), Path("tmp.mp4"), topaz.AI_UPSCALE_ORIGENERATOR)


# Every version a set of settings has shipped under, and a fingerprint of everything that
# version runs Topaz with. A retune bumps the settings' version in util/topaz.py
# and adds a line here for the new one; it never edits a line already here,
# because outputs on disk already name that version as what made them.
SHIPPED = {
    ("ai_upscale", "v001"): "ba105a7372baef8f",
    ("ai_upscale_t2v", "v001"): "433ce5942b2b7849",
    ("non_ai_upscale", "v001"): "7abba8acb076bb73",
    ("ai_upscale", "v002"): "81093271ab54e32e",
    ("ai_upscale_t2v", "v002"): "aebaf14fdcf41a06",
    ("ai_upscale_origenerator", "v001"): "f1d39dc7491ac14e",
}


def _fingerprint(settings: topaz.Settings) -> str:
    """Every command a set of settings runs -- one per orientation -- bar the two file
    paths and the path to Topaz itself, which are the machine's, not the settings'."""
    argvs = [
        topaz.command(Path("in"), Path("out"), _turned_to_an_example_video(settings, orient))[1:]
        for orient in orientation.SORTED
    ]
    return hashlib.sha256(json.dumps(argvs).encode("utf-8")).hexdigest()[:16]


class TestRetunedSettingsOweANewVersion(unittest.TestCase):
    def test_each_settings_run_the_filters_their_version_shipped_with(self):
        running = {(settings.name, settings.version): _fingerprint(settings) for settings in topaz.ALL_SETTINGS}

        assert {key: SHIPPED.get(key) for key in running} == running, "a set of settings changed under a version outputs already record: bump its version in util/topaz.py, then add the new version's fingerprint to SHIPPED"


class TestWhatAFilesNoteSaysMadeIt(unittest.TestCase):
    def test_a_note_in_the_settings_own_words_names_those_settings(self):
        for settings in topaz.ALL_SETTINGS:
            with self.subTest(settings=settings.name):
                assert topaz.settings_noted(settings.videoai_tag) is settings

    def test_a_note_written_before_the_ai_settings_kept_sound_names_the_version_that_wrote_it(self):
        for retired in topaz.RETIRED_SETTINGS:
            with self.subTest(settings=retired.name):
                noted = topaz.settings_noted(retired.videoai_tag)

                assert (noted.name, noted.version, noted.keep_audio) == (retired.name, "v001", False)

    def test_a_note_differing_only_in_the_name_in_parentheses_at_its_end_names_it_too(self):
        """The text-to-video settings' note once named a site in those parentheses,
        and the files written then still say which settings made them."""
        note = topaz.AI_UPSCALE_T2V.videoai_tag
        written_then = note[:note.rindex("(")] + "(t2v examplesite)"

        assert written_then != note
        assert topaz.settings_noted(written_then) is topaz.AI_UPSCALE_T2V

    def test_a_note_in_topazs_own_words_or_no_note_at_all_names_no_settings(self):
        """Topaz describes an export made by hand in its own phrasing; that, or a
        file carrying no note, was not made by any settings here."""
        for note in (("Processed using apo-8 replacing duplicate frames. Enhanced using gcg-5. "
                      "4x upscale"), ""):
            with self.subTest(note=note):
                assert topaz.settings_noted(note) is None


class TestEnvironment(unittest.TestCase):
    def test_points_topaz_at_the_model_directory(self):
        env = topaz.environment()
        assert env["TVAI_MODEL_DIR"] == str(config.TVAI_MODEL_DIR)
        assert env["TVAI_MODEL_DATA_DIR"] == str(config.TVAI_MODEL_DIR)


def topaz_check_reporting(log: str):
    return patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", log))


class TestSignInExpired(unittest.TestCase):
    def test_topaz_saying_its_sign_in_token_expired_means_the_sign_in_expired(self):
        log = ("INFO:  Authentication token expired\n"
               "INFO:  Will attempt to refresh\n"
               "INFO:  Refresh succeeded. Reusing existing license.\n")
        with topaz_check_reporting(log):
            assert topaz.sign_in_expired()

    def test_topaz_failing_to_authenticate_or_turning_its_watermark_on_means_the_same(self):
        for log in ("ERROR: Authentication Failure: login to your account using the login tool\n",
                    "WARNING: Refresh failed. Watermark will be enabled\n"):
            with self.subTest(log=log), topaz_check_reporting(log):
                assert topaz.sign_in_expired()

    def test_a_check_that_reports_no_expiry_means_the_sign_in_is_good(self):
        with topaz_check_reporting("INFO:  Relogin valid\nINFO:  Auth Check Watermark: 0 0 0\n"):
            assert not topaz.sign_in_expired()

    def test_the_check_is_a_tiny_verbose_topaz_run_with_no_window_and_a_time_limit(self):
        with topaz_check_reporting("") as run:
            topaz.sign_in_expired()

        argv, kwargs = run.call_args.args[0], run.call_args.kwargs
        assert argv[0] == str(config.FFMPEG)
        assert argv[argv.index("-loglevel") + 1] == "verbose"
        assert "tvai_up" in argv[argv.index("-vf") + 1]
        assert argv[-3:] == ["-f", "null", "-"]
        assert kwargs["env"]["TVAI_MODEL_DIR"] == str(config.TVAI_MODEL_DIR)
        assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kwargs["timeout"] > 0

    def test_a_check_that_cannot_run_does_not_claim_the_sign_in_expired(self):
        for failure in (OSError("no ffmpeg"), subprocess.TimeoutExpired("ffmpeg", 90)):
            with self.subTest(failure=failure), \
                 patch("subprocess.run", side_effect=failure), \
                 self.assertLogs("util.topaz", level="WARNING"):
                assert not topaz.sign_in_expired()


if __name__ == "__main__":
    unittest.main()
