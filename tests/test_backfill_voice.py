from __future__ import annotations

import array
import json
import sys
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from voice_core.listener import Engines, PauseSettings
from voice_core.whisper_reader import WhisperReader

import config
from backfill.voice import VoiceListener

PHRASES = ["side beta", "undo"]
PAUSES = PauseSettings()
LOUD_FRAME = array.array("h", [2000, -2000] * (PAUSES.frame_samples // 2)).tobytes()
QUIET_FRAME = bytes(PAUSES.frame_samples * 2)
PATIENCE_S = 10.0


def _said(*readings, forming=()):
    return list(forming), list(readings)


class _ScriptedRecognizer:
    def __init__(self, utterances):
        self._utterances = list(utterances)
        self._forming: list[str] = []
        self._readings: list[str] = []
        self._partial = ""

    def SetWords(self, enable):  # noqa: N802 - vosk's own name
        pass

    def SetMaxAlternatives(self, count):  # noqa: N802 - vosk's own name
        pass

    def Reset(self):  # noqa: N802 - vosk's own name
        self._forming, self._readings = self._utterances.pop(0) if self._utterances else ([], [])
        self._partial = ""

    def AcceptWaveform(self, _frame):  # noqa: N802 - vosk's own name
        if self._forming:
            self._partial = self._forming.pop(0)
        return False

    def PartialResult(self):  # noqa: N802 - vosk's own name
        return json.dumps({"partial": self._partial})

    def FinalResult(self):  # noqa: N802 - vosk's own name
        return json.dumps({"alternatives": [
            {"text": reading, "confidence": 1.0} for reading in self._readings]})


def _frames_saying(utterances):
    frames = [QUIET_FRAME] * PAUSES.calibration_frames
    for forming, _ in utterances:
        frames += [LOUD_FRAME] * max(len(forming), PAUSES.min_speech_frames)
        frames += [QUIET_FRAME] * PAUSES.hangover_frames
    return frames


def _engines(utterances, *, streams=None, **more):
    devices = [{"name": "Desk mic", "max_input_channels": 1, "hostapi": 0}]
    streams = [] if streams is None else streams

    @contextmanager
    def stream(**kwargs):
        streams.append("opened")
        for frame in _frames_saying(utterances):
            kwargs["callback"](frame, len(frame) // 2, None, None)
        try:
            yield
        finally:
            streams.append("closed")

    return Engines(
        vosk=SimpleNamespace(Model=lambda model_name: model_name,
                             KaldiRecognizer=lambda *args: _ScriptedRecognizer(utterances)),
        sounddevice=SimpleNamespace(
            default=SimpleNamespace(device=(0, 0)),
            query_devices=lambda index=None: devices if index is None else devices[index],
            RawInputStream=stream),
        **more)


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
    return _told_by(VoiceListener(PHRASES, engines=_engines(steps, **more)),
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
        told = _listen([_said("side beta")], until_heard="side beta")

        self.assertEqual(told.heard, ["side beta"])

    def test_the_words_still_forming_are_shown_as_they_change_and_cleared_before_the_phrase(self):
        told = _listen([_said("side beta", forming=["side", "side", "side beta"])],
                       until_heard="side beta")

        self.assertEqual(told.timeline, [("hearing", "side"), ("hearing", "side beta"),
                                         ("hearing", ""), ("heard", "side beta")])

    def test_what_is_said_outside_the_phrases_is_not_handed_to_the_window(self):
        told = _listen([_said("beta side undo"), _said("side beta")], until_heard="side beta")

        self.assertEqual(told.heard, ["side beta"])


class TestWhenListeningCannotGoOn(unittest.TestCase):
    """The tiles still work, so the window stays open; what it must not do is go on
    looking like it is listening."""

    def test_an_audio_stack_that_is_not_installed_is_a_crash_with_its_reason(self):
        with patch.dict(sys.modules, {"vosk": None}),                 self.assertLogs("backfill.voice", level="ERROR") as logged:
            told = _told_by(VoiceListener(PHRASES))

        self.assertEqual([record.getMessage() for record in logged.records],
                         ["Voice listener crashed"])
        self.assertEqual(len(told.failures), 1)
        self.assertTrue(told.failures[0])

    def test_a_microphone_that_will_not_open_says_so_rather_than_crashed(self):
        engines = _engines([])
        engines.sounddevice.RawInputStream = Mock(side_effect=OSError("no input device"))

        with self.assertLogs("backfill.voice", level="ERROR") as logged:
            told = _told_by(VoiceListener(PHRASES, engines=engines))

        self.assertEqual([record.getMessage() for record in logged.records],
                         ["Microphone could not be opened"])
        self.assertEqual(told.failures, ["no input device"])

    def test_a_recognizer_that_breaks_partway_says_listening_stopped(self):
        engines = _engines([_said(forming=["side"])])
        engines.vosk.KaldiRecognizer = Mock(return_value=Mock(
            AcceptWaveform=Mock(side_effect=RuntimeError("the decoder gave up"))))

        with self.assertLogs("backfill.voice", level="ERROR") as logged:
            told = _told_by(VoiceListener(PHRASES, engines=engines))

        self.assertEqual([record.getMessage() for record in logged.records],
                         ["Voice listener stopped listening"])
        self.assertEqual(told.failures, ["the decoder gave up"])

    def test_a_failure_with_nothing_to_say_for_itself_is_named_for_what_it_is(self):
        engines = _engines([_said(forming=["side"])])
        engines.vosk.KaldiRecognizer = Mock(return_value=Mock(
            AcceptWaveform=Mock(side_effect=RuntimeError())))

        with self.assertLogs("backfill.voice", level="ERROR"):
            told = _told_by(VoiceListener(PHRASES, engines=engines))

        self.assertEqual(told.failures, ["RuntimeError"])


class TestStoppingAndRestarting(unittest.TestCase):
    def test_stop_returns_only_once_the_microphone_is_closed(self):
        """The loop runs inside a PortAudio stream, so returning sooner lets the
        interpreter tear down while a C callback thread is still live in it."""
        streams = []
        _listen([_said("side beta")], until_heard="side beta", streams=streams)

        self.assertEqual(streams, ["opened", "closed"])

    def test_starting_twice_opens_one_microphone(self):
        streams = []
        listener = VoiceListener(
            PHRASES, engines=_engines([_said("side beta")], streams=streams))
        told = _Told(listener, until_heard="side beta")

        listener.start()
        listener.start()
        told.wait()
        listener.stop()

        self.assertEqual(streams, ["opened", "closed"])

    def test_a_stopped_listener_can_be_started_again_and_hears_again(self):
        listener = VoiceListener(PHRASES, engines=_engines([_said("side beta")]))

        _told_by(listener, until_heard="side beta")
        again = _told_by(listener, until_heard="side beta")

        self.assertEqual(again.heard, ["side beta"])

    def test_stopping_one_that_never_started_is_not_an_error(self):
        VoiceListener(PHRASES).stop()


class TestWhichReadingsAreTrusted(unittest.TestCase):
    def test_a_phrase_ranked_under_a_near_miss_is_still_taken(self):
        told = _listen([_said("side side beta", "side beta")], until_heard="side beta")

        self.assertEqual(told.heard, ["side beta"])

    def test_a_phrase_that_discards_the_clip_is_taken_only_as_the_first_reading(self):
        listener = VoiceListener(
            ["trash", "same", "undo"], never_repaired={"trash"},
            engines=_engines([_said("trash same", "trash"), _said("undo")]))

        told = _told_by(listener, until_heard="undo")

        self.assertEqual(told.heard, ["undo"])

    def test_a_phrase_the_second_listener_reads_differently_does_not_act(self):
        told = _listen([_said("side beta"), _said("undo")], until_heard="undo",
                       second_opinion=lambda audio, hint: "and then" if "beta" in hint else hint)

        self.assertEqual(told.heard, ["undo"])

    def test_left_to_itself_it_has_whisper_read_each_command_too(self):
        with patch("backfill.voice.CommandListener") as built:
            listener = VoiceListener(PHRASES)
            listener.start()
            listener.stop()

        engines = built.call_args.args[3]
        self.assertIsInstance(engines.second_opinion, WhisperReader)


class TestWhatItListensWith(unittest.TestCase):
    def test_the_model_the_microphone_the_rate_and_the_bar_are_the_settings_own(self):
        with patch("backfill.voice.CommandListener") as built,                 patch.multiple(config, VOICE_MODEL_NAME="a-model", VOICE_DEVICE_NAME="desk",
                               VOICE_SAMPLE_RATE=8000, VOICE_CONFIDENCE_THRESHOLD=0.5):
            listener = VoiceListener(PHRASES)
            listener.start()
            listener.stop()

        rules, settings = built.call_args.args[:2]
        self.assertEqual((settings.model_name, settings.device_name, settings.sample_rate),
                         ("a-model", "desk", 8000))
        self.assertEqual(rules.confidence_threshold, 0.5)
        self.assertEqual(rules.phrases, frozenset(PHRASES))


if __name__ == "__main__":
    unittest.main()
