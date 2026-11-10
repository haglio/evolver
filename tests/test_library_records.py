from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pytest
from app_support import watch_weights

from tests.product_sources import PROJECT_ROOT, literals_in, product_sources
from util import library_records, watch

_OWNER = "util/library_records.py"

_THE_JOURNAL_LINES_ACT_FIELD = ("util/warm_gun.py", "action")
_A_JOBS_AND_A_PROVIDERS_WORD_TOO = "source"


def _module_level_strings(name: str) -> set[str]:
    tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
    return {node.value.value for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)}


class TestWhereTheNamesComeFrom(unittest.TestCase):
    @pytest.mark.repo_check
    def test_names_are_read_from_their_declaring_module(self):
        declared_elsewhere = {(name, value) for name in product_sources(PROJECT_ROOT) if name != _OWNER
                              for value in _module_level_strings(name)}

        spelled_again = sorted(
            f"{_OWNER}:{node.lineno} {node.value!r}, declared in {name}"
            for node in literals_in(_OWNER)
            for name, value in declared_elsewhere
            if value == node.value and (name, value) != _THE_JOURNAL_LINES_ACT_FIELD)

        assert spelled_again == []

    @pytest.mark.repo_check
    def test_the_clip_blocks_words_are_spelled_only_where_they_are_declared(self):
        words = {library_records.CLIP_BLOCK, *library_records.CLIP_FIELDS_WRITTEN_WHEN_A_CLIP_IS_CUT,
                 *library_records.CLIP_FIELDS_THE_CLIP_MATCH_ADDS} - {_A_JOBS_AND_A_PROVIDERS_WORD_TOO}
        declared_in = dict.fromkeys(words, "no module, under no name")
        declared_in |= {value: name for name in product_sources(PROJECT_ROOT)
                        for value in _module_level_strings(name) if value in words}

        spelled_again = sorted(
            f"{name}:{node.lineno} {node.value!r}, declared in {declared_in[node.value]}"
            for name in product_sources(PROJECT_ROOT)
            for node in literals_in(name)
            if node.value in words and name != declared_in[node.value])

        assert spelled_again == []


class TestTheWatchBlock(unittest.TestCase):
    def test_the_stamped_weight_is_the_one_playlists_draw_by(self):
        stamped = watch.stamped({}, {"completions": 3, "skips": 0, "locks": 0})

        drawn_by = watch_weights.weight_of(stamped)

        assert drawn_by == stamped[watch.BLOCK][library_records.WATCH_WEIGHT_FIELD]
        assert drawn_by != watch_weights.NEUTRAL_WEIGHT


if __name__ == "__main__":
    unittest.main()
