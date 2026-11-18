from __future__ import annotations

import unittest

import pytest

from gui.stage_details import SENTENCES
from tests.product_sources import PROJECT_ROOT, literals_in, product_sources
from util import orientation

_OWNER = "util/orientation.py"
_THE_DETAILS_COLUMN = "gui/stage_details.py"
_COUNTS_A_STAGE_RECORDS = {part.key for sentence in SENTENCES.values() for part in sentence.parts}


def _a_count_named_like_an_orientation(name: str, word: str) -> bool:
    return name == _THE_DETAILS_COLUMN and word in _COUNTS_A_STAGE_RECORDS

class TestTheOrientations(unittest.TestCase):
    def test_the_walk_order_is_the_two_folder_names(self):
        assert orientation.SORTED == (orientation.LANDSCAPE, orientation.PORTRAIT)

    def test_unknown_is_not_a_folder(self):
        assert orientation.UNKNOWN not in orientation.SORTED


class TestOnlyOneModuleSpellsThem(unittest.TestCase):
    @pytest.mark.repo_check
    def test_each_orientation_word_is_spelled_in_one_place(self):
        wanted = {orientation.LANDSCAPE, orientation.PORTRAIT, orientation.UNKNOWN}
        offenders = []
        for name in product_sources(PROJECT_ROOT):
            if name == _OWNER:
                continue
            offenders += [
                f"{name}:{node.lineno}" for node in literals_in(name)
                if node.value in wanted and not _a_count_named_like_an_orientation(name, node.value)
            ]

        assert offenders == [], "the orientations belong to util.orientation -- LANDSCAPE, PORTRAIT, UNKNOWN, and SORTED for the walk order"


if __name__ == "__main__":
    unittest.main()
