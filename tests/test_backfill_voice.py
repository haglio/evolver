from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from voice_core.listener import PauseSettings
from voice_core.speech import HearsSpeech
from voice_core.testing import said, scripted_engines
from voice_core.whisper_reader import WhisperReader

import config
from backfill.voice import VoiceListener

PHRASES = ["side beta", "undo"]
PAUSES = PauseSettings()
PATIENCE_S = 10.0


class _Told:
    """What a listener told the window, and a way to wait for the last of it."""

    def __init__(self, listener, *, until_heard):
        self.heard: list[str] = []
        self.failures: list[str] = []
        self.timeline: list[tuple[str, str]] = []
        self._until_heard = until_heard
        self._done = threading.Event()
        # Direct: the listener speaks from its own thread, and no event loop runs here
        # to carry a queued signal across to this one.
        listener.heard.connect(self._on_heard, Qt.ConnectionType.DirectConnection)
        listener.hearing.connect(self._on_hearing, Qt.ConnectionType.DirectConnection)
        listener.failed.connect(self._on_failed, Qt.ConnectionType.DirectConnection)

    def _on_hearing(self, forming):
        self.timeline.append(("hearing", forming))

    def _on_heard(self, phrase):
        self.heard.append(phrase)
        self.timeline.append(("heard", phrase))
        if phrase == self._until_heard:
            self._done.set()

    def _on_failed(self, reason):
        self.failures.append(reason)
        self._done.set()

    def wait(self):
        assert self._done.wait(PATIENCE_S), "the listener never got that far"


def _listen(steps, *, until_heard, **more):
    return _told_by(VoiceListener(PHRASES, engines=scripted_engines(steps, **more)),
                    until_heard=until_heard)


def _told_by(listener, *, until_heard=None):
    told = _Told(listener, until_heard=until_heard)
    listener.start()
    try:
        told.wait()
    finally:
        listener.stop()
    return told


class TestWhatTheWindowIsTold(unittest.TestCase):
    def test_a_settled_phrase_reaches_the_window(self):
        told = _listen([said("side beta")], until_heard="side beta")

        assert told.heard == ["side beta"]

    def test_the_words_still_forming_are_shown_as_they_change_and_cleared_before_the_phrase(self):
        forming = ["side"] * PAUSES.min_speech_frames + ["side beta"]
        told = _listen([said("side beta", forming=forming)], until_heard="side beta")

        assert told.timeline == [("hearing", "side"), ("hearing", "side beta"), ("hearing", ""), ("heard", "side beta")]

    def test_what_is_said_outside_the_phrases_is_not_handed_to_the_window(self):
        told = _listen([said("beta side undo"), said("side beta")], until_heard="side beta")

        assert told.heard == ["side beta"]


class TestWhenListeningCannotGoOn(unittest.TestCase):
    """The tiles still work, so the window stays open; what it must not do is go on
    looking like it is listening."""

    def test_an_audio_stack_that_is_not_installed_is_a_crash_with_its_reason(self):
        with patch.dict(sys.modules, {"vosk": None}),                 self.assertLogs("backfill.voice", level="ERROR") as logged:
            told = _told_by(VoiceListener(PHRASES))

        assert [record.getMessage() for record in logged.records] == ["Voice listener crashed"]
        assert len(told.failures) == 1
        assert told.failures[0]

    def test_a_microphone_that_will_not_open_says_so_rather_than_crashed(self):
        engines = scripted_engines([])
        engines.sounddevice.RawInputStream = Mock(side_effect=OSError("no input device"))

        with self.assertLogs("backfill.voice", level="ERROR") as logged:
            told = _told_by(VoiceListener(PHRASES, engines=engines))

        assert [record.getMessage() for record in logged.records] == ["Microphone could not be opened"]
        assert told.failures == ["no input device"]

    def test_a_recognizer_that_breaks_partway_says_listening_stopped(self):
        engines = scripted_engines([said(forming=["side"])])
        engines.vosk.KaldiRecognizer = Mock(return_value=Mock(
            AcceptWaveform=Mock(side_effect=RuntimeError("the decoder gave up"))))

        with self.assertLogs("backfill.voice", level="ERROR") as logged:
            told = _told_by(VoiceListener(PHRASES, engines=engines))

        assert [record.getMessage() for record in logged.records] == ["Voice listener stopped listening"]
        assert told.failures == ["the decoder gave up"]

    def test_a_failure_with_nothing_to_say_for_itself_is_named_for_what_it_is(self):
        engines = scripted_engines([said(forming=["side"])])
        engines.vosk.KaldiRecognizer = Mock(return_value=Mock(
            AcceptWaveform=Mock(side_effect=RuntimeError())))

        with self.assertLogs("backfill.voice", level="ERROR"):
            told = _told_by(VoiceListener(PHRASES, engines=engines))

        assert told.failures == ["RuntimeError"]


class TestStoppingAndRestarting(unittest.TestCase):
    def test_stop_returns_only_once_the_microphone_is_closed(self):
        """The loop runs inside a PortAudio stream, so returning sooner lets the
        interpreter tear down while a C callback thread is still live in it."""
        engines = scripted_engines([said("side beta")])
        _told_by(VoiceListener(PHRASES, engines=engines), until_heard="side beta")

        assert (len(engines.sounddevice.opened), engines.sounddevice.closed) == (1, 1)

    def test_starting_twice_opens_one_microphone(self):
        engines = scripted_engines([said("side beta")])
        listener = VoiceListener(PHRASES, engines=engines)
        told = _Told(listener, until_heard="side beta")

        listener.start()
        listener.start()
        told.wait()
        listener.stop()

        assert (len(engines.sounddevice.opened), engines.sounddevice.closed) == (1, 1)

    def test_a_stopped_listener_can_be_started_again_and_hears_again(self):
        listener = VoiceListener(PHRASES, engines=scripted_engines([said("side beta")]))

        _told_by(listener, until_heard="side beta")
        again = _told_by(listener, until_heard="side beta")

        assert again.heard == ["side beta"]

    def test_stopping_one_that_never_started_is_not_an_error(self):
        VoiceListener(PHRASES).stop()


class TestWhichReadingsAreTrusted(unittest.TestCase):
    def test_a_phrase_ranked_under_a_near_miss_is_still_taken(self):
        told = _listen([said("side side beta", "side beta")], until_heard="side beta")

        assert told.heard == ["side beta"]

    def test_a_phrase_that_discards_the_clip_is_taken_only_as_the_first_reading(self):
        listener = VoiceListener(
            ["trash", "same", "undo"], never_repaired={"trash"},
            engines=scripted_engines([said("trash same", "trash"), said("undo")]))

        told = _told_by(listener, until_heard="undo")

        assert told.heard == ["undo"]

    def test_a_phrase_the_verifying_listener_reads_differently_does_not_act(self):
        told = _listen([said("side beta"), said("undo")], until_heard="undo",
                       verifying_listener=lambda audio, hint: "and then" if "beta" in hint else hint)

        assert told.heard == ["undo"]

    def test_left_to_itself_it_has_whisper_read_each_command_and_ends_one_when_its_speaker_pauses(self):
        with patch("backfill.voice.CommandListener") as built:
            listener = VoiceListener(PHRASES)
            listener.start()
            listener.stop()

        engines = built.call_args.args[3]
        assert (type(engines.verifying_listener), type(engines.hears_speech)) == (WhisperReader, HearsSpeech)


class TestWhatItListensWith(unittest.TestCase):
    def test_the_microphone_and_model_are_the_familys_and_the_rate_and_bar_evolvers(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = Path(folder) / "settings.json"
            settings.write_text(json.dumps({"microphone": "desk", "vosk_model": "a-model"}), encoding="utf-8")
            with (patch("backfill.voice.CommandListener") as built,
                  patch.dict(os.environ, {"HAGLIO_SETTINGS": str(settings)}),
                  patch.multiple(config, VOICE_SAMPLE_RATE=8000, VOICE_CONFIDENCE_THRESHOLD=0.5)):
                listener = VoiceListener(PHRASES)
                listener.start()
                listener.stop()

        rules, settings = built.call_args.args[:2]
        assert (settings.model_name, settings.device_name, settings.sample_rate) == ("a-model", "desk", 8000)
        assert rules.confidence_threshold == 0.5
        assert rules.phrases == frozenset(PHRASES)

if __name__ == "__main__":
    unittest.main()
