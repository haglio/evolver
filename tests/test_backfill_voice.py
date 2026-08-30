import json
import sys
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


if __name__ == "__main__":
    unittest.main()


class TestAMissingAudioStack(unittest.TestCase):
    def test_it_is_reported_through_the_one_handler_that_wraps_the_run(self):
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
