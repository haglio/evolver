from __future__ import annotations

import unittest

import pytest

from tests.product_sources import PROJECT_ROOT, literals_in, product_sources
from util import orientation

_OWNER = "util/orientation.py"

_ORIGENERATORS_WORKFLOW_NAME_FOR_A_FOUND_CLIP = {("tasks/origenerator_metadata.py", orientation.UNKNOWN)}


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
                if node.value in wanted and (name, node.value) not in _ORIGENERATORS_WORKFLOW_NAME_FOR_A_FOUND_CLIP
            ]

        assert offenders == [], "the orientations belong to util.orientation -- LANDSCAPE, PORTRAIT, UNKNOWN, and SORTED for the walk order"


if __name__ == "__main__":
    unittest.main()
