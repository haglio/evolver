from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backfill.vocabulary import SAME, SKIP, UNDO, WEIRD, Act, Command, load_vocabulary
from content_overlay import EXAMPLE_CONTENT
from tests.vocabulary_support import vocabulary_of

VOCABULARY = vocabulary_of(
    Act("alpha", "Alpha", aliases=("alpha form",)),
    Act("beta", "Beta"),
    Act("dance", "Dancing", aliases=("dancing",)),
    Act("other", "Other"),
)


class TestActions(unittest.TestCase):
    def test_a_camera_word_scopes_every_act(self):
        self.assertEqual(VOCABULARY.actions["side beta"], "Side Beta")
        self.assertEqual(VOCABULARY.actions["xyz beta"], "XYZ Beta")

    def test_no_act_has_a_bare_camera_less_form(self):
        for bare in ("alpha", "alpha form", "beta", "dance", "dancing", "other"):
            self.assertNotIn(bare, VOCABULARY.actions)

    def test_a_camera_is_heard_under_each_of_its_aliases(self):
        self.assertEqual(VOCABULARY.actions["x y z beta"], "XYZ Beta")
        self.assertEqual(VOCABULARY.actions["xyz beta"], "XYZ Beta")

    def test_dance_and_other_are_scoped_by_a_camera_word_too(self):
        self.assertEqual(VOCABULARY.actions["side dance"], "Side Dancing")
        self.assertEqual(VOCABULARY.actions["xyz dance"], "XYZ Dancing")
        self.assertEqual(VOCABULARY.actions["side other"], "Side Other")
        self.assertEqual(VOCABULARY.actions["x y z other"], "XYZ Other")

    def test_every_way_of_saying_the_camera_pairs_with_every_way_of_saying_the_act(self):
        self.assertEqual(
            {phrase for phrase, action in VOCABULARY.actions.items() if action == "XYZ Alpha"},
            {"xyz alpha", "xyz alpha form", "x y z alpha", "x y z alpha form"},
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

    def test_the_phrases_that_discard_a_clip_are_every_way_of_saying_weird(self):
        self.assertEqual(VOCABULARY.discarding_phrases(), {"weird", "trash"})

    def test_no_phrase_is_both_an_action_and_a_control(self):
        self.assertEqual(set(VOCABULARY.actions) & set(VOCABULARY.controls), set())


class TestCommandGrid(unittest.TestCase):
    def _row(self, action):
        return next(row for row in VOCABULARY.scoped_grid() if row[0].label == f"Side {action}")

    def test_every_row_is_a_cell_per_camera_in_their_order_with_no_bare_column(self):
        for first, second in VOCABULARY.scoped_grid():
            self.assertTrue(first.label.startswith("Side "), first.label)
            self.assertTrue(second.label.startswith("XYZ "), second.label)

    def test_a_row_pairs_the_spoken_phrase_with_the_action_each_cell_records(self):
        first, second = self._row("Beta")
        self.assertEqual(first, Command("side beta", "Side Beta"))
        self.assertEqual(second, Command("xyz beta", "XYZ Beta"))

    def test_an_act_with_alias_forms_shows_a_single_canonical_row(self):
        """Alpha is heard two ways ("alpha"/"alpha form") but is one tile."""
        alpha_rows = [row for row in VOCABULARY.scoped_grid() if row[0].label == "Side Alpha"]
        self.assertEqual(len(alpha_rows), 1)
        self.assertEqual(alpha_rows[0][0], Command("side alpha", "Side Alpha"))

    def test_dance_and_other_are_scoped_rows_in_the_grid_too(self):
        self.assertEqual(self._row("Dancing")[1], Command("xyz dance", "XYZ Dancing"))
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


_CAMERAS = [
    {"spoken": "north", "prefix": "North"},
    {"spoken": "qrs", "prefix": "QRS", "aliases": ["q r s"]},
]


class TestTheOverlaysTables(unittest.TestCase):
    def _loaded(self, *acts):
        overlay = {"acts": list(acts), "cameras": _CAMERAS}
        with patch("backfill.vocabulary.load_content", return_value=overlay):
            return load_vocabulary()

    def test_each_act_the_overlay_lists_is_a_row_of_the_grid(self):
        vocabulary = self._loaded({"spoken": "kappa", "action": "Kappa", "aliases": ["kappa form"]})

        self.assertEqual(
            vocabulary.scoped_grid(),
            [[Command("north kappa", "North Kappa"), Command("qrs kappa", "QRS Kappa")]],
        )
        self.assertEqual(vocabulary.actions["north kappa form"], "North Kappa")

    def test_an_act_listed_without_aliases_is_voiced_one_way(self):
        vocabulary = self._loaded({"spoken": "kappa", "action": "Kappa"})

        self.assertEqual(sorted(vocabulary.actions), ["north kappa", "q r s kappa", "qrs kappa"])

    def test_each_camera_the_overlay_lists_is_a_column_heard_under_its_aliases(self):
        vocabulary = self._loaded({"spoken": "kappa", "action": "Kappa"})

        self.assertEqual(
            [cell.label for cell in vocabulary.scoped_grid()[0]], ["North Kappa", "QRS Kappa"])
        self.assertEqual(vocabulary.actions["q r s kappa"], "QRS Kappa")

    def test_the_overlay_is_read_each_time_a_vocabulary_is_asked_for(self):
        first = self._loaded({"spoken": "kappa", "action": "Kappa"})
        second = self._loaded({"spoken": "lambda", "action": "Lambda"})

        self.assertEqual([row[0].label for row in first.scoped_grid()], ["North Kappa"])
        self.assertEqual([row[0].label for row in second.scoped_grid()], ["North Lambda"])


if __name__ == "__main__":
    unittest.main()
