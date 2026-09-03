"""The two orientations the library files a video under, in one place.

The value ffprobe produces, the directory name a path is built from, and the
folder names four stages walk were three separate spellings of the same three
strings across six modules, with nothing connecting them: a typo in any one was
a silently empty listing rather than an error.
"""

import ast
import unittest
from pathlib import Path

from tests.test_dead_code import PROJECT_ROOT, _source_files
from tests.test_variants import _string_constants
from util import orientation

# The module that owns them, plus the one that names them in an assertion of
# its own -- this file.
_OWNER = "util/orientation.py"


class TestTheOrientations(unittest.TestCase):
    def test_the_walk_order_is_the_two_folder_names(self):
        self.assertEqual(
            orientation.SORTED, (orientation.LANDSCAPE, orientation.PORTRAIT)
        )

    def test_the_third_answer_is_not_one_of_the_two(self):
        """A video ffprobe cannot measure is left where it is rather than
        guessed into a folder, so UNKNOWN must never pass a `in SORTED` test."""
        self.assertNotIn(orientation.UNKNOWN, orientation.SORTED)


class TestOnlyOneModuleSpellsThem(unittest.TestCase):
    def test_the_three_strings_are_literals_in_exactly_one_place(self):
        wanted = {orientation.LANDSCAPE, orientation.PORTRAIT, orientation.UNKNOWN}
        offenders = []
        for name in _source_files(PROJECT_ROOT):
            if name == _OWNER:
                continue
            tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
            offenders += [
                f"{name}:{node.lineno}" for node in _string_constants(tree)
                if node.value in wanted
            ]

        self.assertEqual(
            offenders,
            [],
            "the orientations belong to util.orientation -- LANDSCAPE, PORTRAIT, "
            "UNKNOWN, and SORTED for the walk order",
        )


if __name__ == "__main__":
    unittest.main()
