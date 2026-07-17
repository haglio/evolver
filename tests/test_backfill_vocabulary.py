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

    def test_same_repeats_the_last_action(self):
        self.assertEqual(vocabulary.CONTROLS["same"], vocabulary.SAME)

    def test_no_phrase_is_both_an_action_and_a_control(self):
        self.assertEqual(set(vocabulary.ACTIONS) & set(vocabulary.CONTROLS), set())


class TestCommandGrid(unittest.TestCase):
    def _row(self, action):
        return next(row for row in vocabulary.scoped_grid() if row[0].label == action)

    def test_the_bare_column_leads_the_camera_columns(self):
        self.assertEqual(vocabulary.CAMERA_COLUMNS[0], "")
        self.assertEqual(vocabulary.CAMERA_COLUMNS[1:], ("Side", "POV"))

    def test_each_row_carries_one_command_per_camera_column(self):
        for row in vocabulary.scoped_grid():
            self.assertEqual(len(row), len(vocabulary.CAMERA_COLUMNS))

    def test_a_row_pairs_the_spoken_phrase_with_the_action_each_cell_records(self):
        bare, side, pov = self._row("Gamma")
        self.assertEqual(bare, vocabulary.Command("gamma", "Gamma"))
        self.assertEqual(side, vocabulary.Command("side gamma", "Side Gamma"))
        self.assertEqual(pov, vocabulary.Command("pov gamma", "Pov Gamma"))

    def test_an_act_with_alias_forms_shows_a_single_canonical_row(self):
        """Alpha is heard two ways ("alpha"/"alpha form") but is one tile."""
        alpha_rows = [row for row in vocabulary.scoped_grid() if row[0].label == "Alpha"]
        self.assertEqual(len(alpha_rows), 1)
        self.assertEqual(alpha_rows[0][0], vocabulary.Command("alpha", "Alpha"))

    def test_unscoped_acts_are_one_tile_each_taking_no_camera_word(self):
        self.assertEqual(
            vocabulary.unscoped_commands(),
            [vocabulary.Command("dance", "Dancing"), vocabulary.Command("other", "Other")],
        )

    def test_controls_cover_skip_weird_undo_and_same(self):
        self.assertEqual(
            vocabulary.control_commands(),
            [
                vocabulary.Command("skip", "Skip"),
                vocabulary.Command("weird", "Weird"),
                vocabulary.Command("undo", "Undo"),
                vocabulary.Command("same", "Same"),
            ],
        )

    def test_every_grid_command_is_a_phrase_the_session_understands(self):
        known = set(vocabulary.ACTIONS) | set(vocabulary.CONTROLS)
        rows = [*vocabulary.scoped_grid(), vocabulary.unscoped_commands(), vocabulary.control_commands()]
        for group in rows:
            for command in group:
                self.assertIn(command.phrase, known)


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
