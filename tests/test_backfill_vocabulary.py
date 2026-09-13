from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backfill.vocabulary import SAME, SKIP, UNDO, WEIRD, Act, Command, Vocabulary, load_vocabulary
from content_overlay import EXAMPLE_CONTENT

# Fabricated, in the committed example's placeholder style.
VOCABULARY = Vocabulary([
    Act("alpha", "Alpha", aliases=("alpha form",)),
    Act("beta", "Beta"),
    Act("dance", "Dancing", aliases=("dancing",)),
    Act("other", "Other"),
])


class TestActions(unittest.TestCase):
    def test_a_camera_word_scopes_every_act(self):
        self.assertEqual(VOCABULARY.actions["side beta"], "Side Beta")
        self.assertEqual(VOCABULARY.actions["pov beta"], "POV Beta")

    def test_no_act_has_a_bare_camera_less_form(self):
        for bare in ("alpha", "alpha form", "beta", "dance", "dancing", "other"):
            self.assertNotIn(bare, VOCABULARY.actions)

    def test_pov_is_heard_spelled_out_as_its_three_letters(self):
        """"POV" is an initialism; the lexicon's one-word "pov" is not the letters."""
        self.assertEqual(VOCABULARY.actions["p o v beta"], "POV Beta")
        self.assertEqual(VOCABULARY.actions["pov beta"], "POV Beta")

    def test_dance_and_other_are_scoped_by_a_camera_word_too(self):
        self.assertEqual(VOCABULARY.actions["side dance"], "Side Dancing")
        self.assertEqual(VOCABULARY.actions["pov dance"], "POV Dancing")
        self.assertEqual(VOCABULARY.actions["side other"], "Side Other")
        self.assertEqual(VOCABULARY.actions["p o v other"], "POV Other")

    def test_every_way_of_saying_the_camera_pairs_with_every_way_of_saying_the_act(self):
        self.assertEqual(
            {phrase for phrase, action in VOCABULARY.actions.items() if action == "POV Alpha"},
            {"pov alpha", "pov alpha form", "p o v alpha", "p o v alpha form"},
        )


class TestControls(unittest.TestCase):
    def test_skip_defers_and_both_weird_words_discard(self):
        self.assertEqual(VOCABULARY.controls["skip"], SKIP)
        self.assertEqual(VOCABULARY.controls["weird"], WEIRD)
        self.assertEqual(VOCABULARY.controls["trash"], WEIRD)

    def test_undo_takes_the_last_decision_back(self):
        self.assertEqual(VOCABULARY.controls["undo"], UNDO)

    def test_same_repeats_the_last_action(self):
        self.assertEqual(VOCABULARY.controls["same"], SAME)

    def test_no_phrase_is_both_an_action_and_a_control(self):
        self.assertEqual(set(VOCABULARY.actions) & set(VOCABULARY.controls), set())


class TestCommandGrid(unittest.TestCase):
    def _row(self, action):
        return next(row for row in VOCABULARY.scoped_grid() if row[0].label == f"Side {action}")

    def test_every_row_is_side_then_pov_with_no_bare_column(self):
        for side, pov in VOCABULARY.scoped_grid():
            self.assertTrue(side.label.startswith("Side "), side.label)
            self.assertTrue(pov.label.startswith("POV "), pov.label)

    def test_a_row_pairs_the_spoken_phrase_with_the_action_each_cell_records(self):
        side, pov = self._row("Beta")
        self.assertEqual(side, Command("side beta", "Side Beta"))
        self.assertEqual(pov, Command("pov beta", "POV Beta"))

    def test_an_act_with_alias_forms_shows_a_single_canonical_row(self):
        """Alpha is heard two ways ("alpha"/"alpha form") but is one tile."""
        alpha_rows = [row for row in VOCABULARY.scoped_grid() if row[0].label == "Side Alpha"]
        self.assertEqual(len(alpha_rows), 1)
        self.assertEqual(alpha_rows[0][0], Command("side alpha", "Side Alpha"))

    def test_dance_and_other_are_scoped_rows_in_the_grid_too(self):
        self.assertEqual(self._row("Dancing")[1], Command("pov dance", "POV Dancing"))
        self.assertEqual(self._row("Other")[0], Command("side other", "Side Other"))

    def test_controls_cover_skip_weird_undo_and_same(self):
        self.assertEqual(
            VOCABULARY.control_commands(),
            [
                Command("skip", "Skip"),
                Command("weird", "Weird"),
                Command("undo", "Undo"),
                Command("same", "Same"),
            ],
        )

    def test_every_grid_command_is_a_phrase_the_session_understands(self):
        known = set(VOCABULARY.actions) | set(VOCABULARY.controls)
        groups = [*VOCABULARY.scoped_grid(), VOCABULARY.control_commands()]
        for group in groups:
            for command in group:
                self.assertIn(command.phrase, known)


class TestGrammarPhrases(unittest.TestCase):
    def test_covers_every_action_and_control_phrase(self):
        self.assertEqual(
            VOCABULARY.grammar_phrases(),
            sorted({*VOCABULARY.actions, *VOCABULARY.controls}),
        )

    def test_the_committed_example_spells_every_act_in_words_the_vosk_lexicon_knows(self):
        """The compounds live in the written action, never in a spoken phrase."""
        example = json.loads(EXAMPLE_CONTENT.read_text(encoding="utf-8"))
        with patch("backfill.vocabulary.load_content", return_value=example):
            vocabulary = load_vocabulary()

        spoken_words = set(" ".join(vocabulary.grammar_phrases()).split())
        for act in vocabulary.acts:
            compound = act.action.replace(" ", "").lower()
            if compound in spoken_words:
                # Only allowed when that IS how the act is said, e.g. "other".
                self.assertIn(compound, {form.lower() for form in act.forms()})


class TestTheOverlaysActTable(unittest.TestCase):
    def _loaded(self, *acts):
        with patch("backfill.vocabulary.load_content", return_value={"acts": list(acts)}):
            return load_vocabulary()

    def test_each_act_the_overlay_lists_is_a_row_of_the_grid(self):
        vocabulary = self._loaded({"spoken": "kappa", "action": "Kappa", "aliases": ["kappa form"]})

        self.assertEqual(
            vocabulary.scoped_grid(),
            [[Command("side kappa", "Side Kappa"), Command("pov kappa", "POV Kappa")]],
        )
        self.assertEqual(vocabulary.actions["side kappa form"], "Side Kappa")

    def test_an_act_listed_without_aliases_is_voiced_one_way(self):
        vocabulary = self._loaded({"spoken": "kappa", "action": "Kappa"})

        self.assertEqual(sorted(vocabulary.actions), ["p o v kappa", "pov kappa", "side kappa"])

    def test_the_overlay_is_read_each_time_a_vocabulary_is_asked_for(self):
        first = self._loaded({"spoken": "kappa", "action": "Kappa"})
        second = self._loaded({"spoken": "lambda", "action": "Lambda"})

        self.assertEqual([row[0].label for row in first.scoped_grid()], ["Side Kappa"])
        self.assertEqual([row[0].label for row in second.scoped_grid()], ["Side Lambda"])


if __name__ == "__main__":
    unittest.main()
