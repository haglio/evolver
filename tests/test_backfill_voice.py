from __future__ import annotations

import json
import queue
import sys
import threading
import unittest
from unittest.mock import patch

from backfill.voice import VoiceListener, build_grammar, partial_text, recognized_phrase


class TestBuildGrammar(unittest.TestCase):
    def test_lists_every_phrase_plus_the_unknown_token(self):
        grammar = json.loads(build_grammar(["weird", "dance"]))

        self.assertEqual(grammar, ["dance", "weird", "[unk]"])


class TestRecognizedPhrase(unittest.TestCase):
    def _result(self, text, confidences=None):
        payload = {"text": text}
        if confidences is not None:
            payload["result"] = [{"conf": c} for c in confidences]
        return json.dumps(payload)

    def test_returns_a_phrase_the_grammar_knows(self):
        self.assertEqual(recognized_phrase(self._result("dance"), threshold=0.7), "dance")

    def test_rejects_silence_and_the_unknown_token(self):
        self.assertIsNone(recognized_phrase(self._result(""), threshold=0.7))
        self.assertIsNone(recognized_phrase(self._result("[unk]"), threshold=0.7))

    def test_rejects_a_phrase_heard_too_faintly(self):
        self.assertIsNone(recognized_phrase(self._result("dance", [0.4]), threshold=0.7))

    def test_a_phrase_exactly_at_the_threshold_is_trusted(self):
        # The comparison is strictly-below: at the boundary the phrase passes.
        # Nothing exercised the boundary before, so < could become <= unseen
        # (audit probe 20).
        self.assertEqual(recognized_phrase(self._result("dance", [0.7]), threshold=0.7), "dance")

    def test_accepts_a_phrase_heard_clearly(self):
        self.assertEqual(recognized_phrase(self._result("dance", [0.9]), threshold=0.7), "dance")

    def test_averages_confidence_across_the_words_of_a_phrase(self):
        self.assertEqual(
            recognized_phrase(self._result("side beta", [0.9, 0.9, 0.3]), threshold=0.7),
            "side beta",
        )

    def test_accepts_a_phrase_vosk_gave_no_confidence_for(self):
        """Grammar mode routinely omits per-word confidences."""
        self.assertEqual(recognized_phrase(self._result("dance", []), threshold=0.7), "dance")


class TestPartialText(unittest.TestCase):
    def test_returns_the_live_hypothesis_the_partial_carries(self):
        self.assertEqual(partial_text(json.dumps({"partial": "side eta"})), "side eta")

    def test_empty_when_nothing_has_been_heard_yet(self):
        self.assertEqual(partial_text(json.dumps({"partial": ""})), "")
        self.assertEqual(partial_text(json.dumps({})), "")

    def test_empty_for_the_unknown_token(self):
        self.assertEqual(partial_text(json.dumps({"partial": "[unk]"})), "")

    def test_empty_for_malformed_json(self):
        self.assertEqual(partial_text("not json"), "")


class TestAMissingAudioStack(unittest.TestCase):
    def test_it_is_reported_the_way_every_other_failure_in_this_thread_is(self):
        """vosk and sounddevice are declared runtime dependencies, so a missing
        one is not an expected condition with a friendly message of its own —
        it is a broken install, reported the way every other failure in this
        thread is, and mic.py already imports sounddevice unguarded inside the
        same block."""
        listener = VoiceListener(["side beta"])

        with patch.dict(sys.modules, {"vosk": None}):
            with self.assertLogs("backfill.voice", level="ERROR") as logged:
                listener._run()

        self.assertEqual(len(logged.records), 1)
        self.assertEqual(logged.records[0].getMessage(), "Voice listener crashed")

    def test_a_microphone_that_will_not_open_says_so_rather_than_crashed(self):
        """Three steps, three handlers: a model that will not load and a
        microphone nothing can open are different things to be told, and one
        blanket except around both could only ever say "crashed"."""
        listener = VoiceListener(["side beta"])
        failures = []
        listener.failed.connect(failures.append)

        with patch.object(listener, "_build_recognizer", return_value=object()), \
                patch("backfill.voice._open_stream",
                      side_effect=OSError("no input device")), \
                self.assertLogs("backfill.voice", level="ERROR") as logged:
            listener._run()

        self.assertEqual(logged.records[0].getMessage(),
                         "Microphone could not be opened")
        self.assertEqual(failures, ["no input device"])


class _ScriptedRecognizer:
    """A recognizer that plays a script, one step per audio block.

    Each step is ``("partial", text)`` or ``("final", text)``. It sets the stop
    event on its last step, which is the one thing a real microphone going
    quiet cannot do for a test.
    """

    def __init__(self, steps, stop):
        self._steps = list(steps)
        self._stop = stop
        self._current = ("partial", "")

    def AcceptWaveform(self, _block):  # noqa: N802 - vosk's own name
        self._current = self._steps.pop(0)
        if not self._steps:
            self._stop.set()
        return self._current[0] == "final"

    def PartialResult(self):  # noqa: N802 - vosk's own name
        return json.dumps({"partial": self._current[1]})

    def Result(self):  # noqa: N802 - vosk's own name
        return json.dumps({"text": self._current[1]})


class TestTheListeningLoop(unittest.TestCase):
    """What the recognizer says, and what the window is told about it.

    The loop sat inside the microphone stream's context inside one 56-line
    method, so nothing could reach it without an audio backend and a model on
    disk, and backfill/voice.py was the least-covered file in the unit.
    """

    def setUp(self):
        self.heard: list[str] = []
        self.hearing: list[str] = []
        self.listener = VoiceListener(["side beta"])
        self.listener.heard.connect(self.heard.append)
        self.listener.hearing.connect(self.hearing.append)

    def _play(self, steps):
        audio: queue.Queue[bytes] = queue.Queue()
        for index in range(len(steps)):
            audio.put(bytes([index]))
        self.listener._consume(
            _ScriptedRecognizer(steps, self.listener._stop), audio)

    def test_a_settled_phrase_reaches_the_window(self):
        self._play([("final", "side beta")])

        self.assertEqual(self.heard, ["side beta"])

    def test_the_live_guess_is_shown_while_a_phrase_is_forming(self):
        self._play([("partial", "side"), ("partial", "side beta")])

        self.assertEqual(self.hearing, ["side", "side beta"])
        self.assertEqual(self.heard, [])

    def test_the_same_guess_twice_is_shown_once(self):
        """The recognizer repeats its hypothesis on every block it is unsure
        about, and re-emitting it would repaint the window at the block rate."""
        self._play([("partial", "side"), ("partial", "side"), ("partial", "side")])

        self.assertEqual(self.hearing, ["side"])

    def test_a_settled_phrase_clears_the_live_guess_first(self):
        """The guess is stale the moment the utterance ends, so the window is
        told to drop it before it is told what was heard."""
        self._play([("partial", "side"), ("final", "side beta")])

        self.assertEqual(self.hearing, ["side", ""])
        self.assertEqual(self.heard, ["side beta"])

    def test_a_phrase_outside_the_grammar_is_not_reported_as_heard(self):
        self._play([("final", "[unk]"), ("final", "side beta")])

        self.assertEqual(self.heard, ["side beta"])

    def test_it_stops_without_reading_the_queue_once_the_event_is_set(self):
        """The guard is at the top of the loop: stop() sets the event, and a
        block already queued is not consumed on the way out."""
        audio: queue.Queue[bytes] = queue.Queue()
        audio.put(b"x")
        self.listener._stop.set()

        self.listener._consume(
            _ScriptedRecognizer([("final", "side beta")], self.listener._stop), audio)

        self.assertEqual(audio.qsize(), 1)
        self.assertEqual(self.heard, [])


class TestStoppingAndRestarting(unittest.TestCase):
    """stop() has to actually stop it, and leave it startable again.

    It set an Event and returned: nothing waited for the thread to leave the
    PortAudio stream, so the interpreter could tear down while a C callback
    thread was still live in it. And it never cleared _thread, so the
    `if self._thread is not None: return` guard in start() made a stopped
    listener permanently unstartable.
    """

    def _listener(self):
        listener = VoiceListener(["side beta"])
        # _run is replaced wholesale: the real one wants vosk, a model and a
        # microphone. What is under test is the thread's lifetime.
        return listener

    def test_stop_waits_for_the_thread_to_finish(self):
        listener = self._listener()
        left = threading.Event()

        def body():
            listener._stop.wait(5.0)
            left.set()

        with patch.object(listener, "_run", body):
            listener.start()
            listener.stop()

        self.assertTrue(left.is_set())

    def test_a_stopped_listener_can_be_started_again(self):
        listener = self._listener()
        runs = []

        def body():
            runs.append(1)
            listener._stop.wait(5.0)

        with patch.object(listener, "_run", body):
            listener.start()
            listener.stop()
            listener._stop.clear()
            listener.start()
            listener.stop()

        self.assertEqual(len(runs), 2)

    def test_stopping_one_that_never_started_is_not_an_error(self):
        self._listener().stop()

    def test_starting_twice_runs_one_thread(self):
        listener = self._listener()
        runs = []

        def body():
            runs.append(1)
            listener._stop.wait(5.0)

        with patch.object(listener, "_run", body):
            listener.start()
            listener.start()
            listener.stop()

        self.assertEqual(len(runs), 1)


class TestReportingAFailure(unittest.TestCase):
    def test_a_crash_says_so_rather_than_leaving_the_grid_looking_alive(self):
        """It logged and returned. The window kept showing its command grid with
        no signal that the microphone path was gone, so a user was left clicking
        tiles wondering why speech had stopped working."""
        listener = VoiceListener(["side beta"])
        failures = []
        listener.failed.connect(failures.append)

        with patch.dict(sys.modules, {"vosk": None}):
            with self.assertLogs("backfill.voice", level="ERROR"):
                listener._run()

        self.assertEqual(len(failures), 1)
        self.assertTrue(failures[0])


if __name__ == "__main__":
    unittest.main()
