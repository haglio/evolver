"""Where Genau puts a condemned clip, held to what Genau says it does.

Evolver delivers upscaled clips into the folder Genau plays from and drains the
pile Genau moves a condemned one to.  That pile's place -- beside the folder,
not inside it -- is Genau's rule, and it was written out a second time here,
from reading that repo's source, with nothing comparing the two.  A rename over
there left this repo draining a folder nothing ever writes to, and both suites
stayed green through it.

Genau publishes ``genau_contract.json`` at its checkout root now.  Neither
gate clones the other, so on a machine with no Genau beside this one there is
nothing to compare and the check says so -- that walk is the one place the two
sides can be put side by side at all.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import config

CONTRACT = Path("genau") / "genau_contract.json"


def _promise() -> dict | None:
    """Genau's published document, or ``None`` where it is not beside this.

    Walked up from here rather than resolved through the content overlay: the
    overlay is git-ignored, so a worktree -- which is where every suite runs --
    has only the placeholder one, pointing at a library that is not there.  The
    walk lands on the checkout beside the primary from a worktree and from a
    clone alike.
    """
    for parent in Path(__file__).resolve().parents:
        published = parent / CONTRACT
        if published.is_file():
            return json.loads(published.read_text(encoding="utf-8"))
    return None


class GenauContract(unittest.TestCase):
    def setUp(self):
        self.promise = _promise()
        if self.promise is None:
            self.skipTest(f"no {CONTRACT.as_posix()} beside this checkout")

    def test_the_pile_drained_here_is_where_genau_condemns_a_clip_to(self):
        """Delivered clips and condemned ones are the two ends of one folder
        pair, and only one repo decides its shape."""
        beside = self.promise["beside_the_clips_folder"]

        self.assertEqual(config.GENAU_WEIRD_DIR,
                         config.GENAU_CLIPS_DIR.parent / beside["condemned"])


if __name__ == "__main__":
    unittest.main()
