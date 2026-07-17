import json
import unittest

from backfill.voice import build_grammar, partial_text, recognized_phrase


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

    def test_accepts_a_phrase_heard_clearly(self):
        self.assertEqual(recognized_phrase(self._result("dance", [0.9]), threshold=0.7), "dance")

    def test_averages_confidence_across_the_words_of_a_phrase(self):
        self.assertEqual(
            recognized_phrase(self._result("side gamma", [0.9, 0.9, 0.3]), threshold=0.7),
            "side gamma",
        )

    def test_accepts_a_phrase_vosk_gave_no_confidence_for(self):
        """Grammar mode routinely omits per-word confidences."""
        self.assertEqual(recognized_phrase(self._result("dance", []), threshold=0.7), "dance")


class TestPartialText(unittest.TestCase):
    def test_returns_the_live_hypothesis_the_partial_carries(self):
        self.assertEqual(partial_text(json.dumps({"partial": "side delta"})), "side delta")

    def test_empty_when_nothing_has_been_heard_yet(self):
        self.assertEqual(partial_text(json.dumps({"partial": ""})), "")
        self.assertEqual(partial_text(json.dumps({})), "")

    def test_empty_for_the_unknown_token(self):
        self.assertEqual(partial_text(json.dumps({"partial": "[unk]"})), "")

    def test_empty_for_malformed_json(self):
        self.assertEqual(partial_text("not json"), "")


if __name__ == "__main__":
    unittest.main()
