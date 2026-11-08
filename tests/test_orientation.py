from __future__ import annotations

import ast
import unittest
from pathlib import Path

import pytest

from tests.product_sources import PROJECT_ROOT, product_sources, strings_outside_docstrings
from util import orientation

_OWNER = "util/orientation.py"

_ORIGENERATORS_WORKFLOW_NAME_FOR_A_FOUND_CLIP = {("tasks/origenerator_metadata.py", orientation.UNKNOWN)}


class TestTheOrientations(unittest.TestCase):
    def test_the_walk_order_is_the_two_folder_names(self):
        assert orientation.SORTED == (orientation.LANDSCAPE, orientation.PORTRAIT)

    def test_a_video_ffprobe_cannot_measure_is_never_guessed_into_a_folder(self):
        assert orientation.UNKNOWN not in orientation.SORTED


class TestOnlyOneModuleSpellsThem(unittest.TestCase):
    @pytest.mark.repo_check
    def test_a_stray_spelling_cannot_silently_empty_a_listing_as_each_word_is_spelled_once(self):
        wanted = {orientation.LANDSCAPE, orientation.PORTRAIT, orientation.UNKNOWN}
        offenders = []
        for name in product_sources(PROJECT_ROOT):
            if name == _OWNER:
                continue
            tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
            offenders += [
                f"{name}:{node.lineno}" for node in strings_outside_docstrings(tree)
                if node.value in wanted and (name, node.value) not in _ORIGENERATORS_WORKFLOW_NAME_FOR_A_FOUND_CLIP
            ]

        assert offenders == [], "the orientations belong to util.orientation -- LANDSCAPE, PORTRAIT, UNKNOWN, and SORTED for the walk order"


if __name__ == "__main__":
    unittest.main()
