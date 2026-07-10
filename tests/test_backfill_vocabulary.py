import unittest

from backfill import vocabulary


class TestActions(unittest.TestCase):
    def test_a_bare_act_maps_to_its_canonical_action(self):
        self.assertEqual(vocabulary.ACTIONS["gamma"], "Gamma")

    def test_a_camera_word_prefixes_the_action(self):
        self.assertEqual(vocabulary.ACTIONS["side gamma"], "Side Gamma")
        self.assertEqual(vocabulary.ACTIONS["pov gamma"], "Pov Gamma")

    def test_pov_is_heard_spelled_out_as_its_three_letters(self):
        """"POV" is an initialism; the lexicon's one-word "pov" is not the letters."""
        self.assertEqual(vocabulary.ACTIONS["p o v gamma"], "Pov Gamma")
        self.assertEqual(vocabulary.ACTIONS["pov gamma"], "Pov Gamma")

    def test_dance_and_other_take_no_camera_word(self):
        self.assertEqual(vocabulary.ACTIONS["dance"], "Dancing")
        self.assertEqual(vocabulary.ACTIONS["other"], "Other")
        self.assertNotIn("side dance", vocabulary.ACTIONS)
        self.assertNotIn("pov other", vocabulary.ACTIONS)


class TestControls(unittest.TestCase):
    def test_skip_defers_and_both_weird_words_discard(self):
        self.assertEqual(vocabulary.CONTROLS["skip"], vocabulary.SKIP)
        self.assertEqual(vocabulary.CONTROLS["weird"], vocabulary.WEIRD)
        self.assertEqual(vocabulary.CONTROLS["trash"], vocabulary.WEIRD)

    def test_undo_takes_the_last_decision_back(self):
        self.assertEqual(vocabulary.CONTROLS["undo"], vocabulary.UNDO)

    def test_no_phrase_is_both_an_action_and_a_control(self):
        self.assertEqual(set(vocabulary.ACTIONS) & set(vocabulary.CONTROLS), set())


class TestGrammarPhrases(unittest.TestCase):
    def test_covers_every_action_and_control_phrase(self):
        self.assertEqual(
            vocabulary.grammar_phrases(),
            sorted({*vocabulary.ACTIONS, *vocabulary.CONTROLS}),
        )

    def test_spells_every_act_in_words_the_vosk_lexicon_knows(self):
        """The compounds live in the written action, never in a spoken phrase."""
        spoken = " ".join(vocabulary.grammar_phrases())
        for compound in ("alpha", "gamma", "zeta", "epsilon", "delta"):
            self.assertNotIn(compound, spoken)


if __name__ == "__main__":
    unittest.main()
