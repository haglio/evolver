"""What this repo reads out of Origenerator's gallery, held to what Origenerator promises.

Evolver mounts that database read-only and selects columns off ``generations``
by name.  Every one of those names was spelled here, on the reading side, with
nothing comparing them to the table: a column renamed over there left every row
reading as never sent, and both suites stayed green.

Origenerator publishes ``origenerator_gallery_contract.json`` at its checkout
root now.  These hold this repo's reads to it.  Neither gate clones the other,
so on a machine with no Origenerator beside this one there is nothing to
compare and the check says so.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import config
from tasks import origenerator_metadata, withdrawn
from util import lanes, origenerator_gallery

CONTRACT = Path("origenerator") / origenerator_gallery.PUBLISHED


def _origenerator_beside_this() -> Path | None:
    """The Origenerator checkout publishing its document beside this one, or ``None``.

    Walked up from here rather than resolved through the content overlay: the
    overlay is git-ignored, so a worktree -- which is where every suite runs --
    has only the placeholder one, pointing at a library that is not there.  The
    walk lands on the checkout beside the primary from a worktree and from a
    clone alike.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / CONTRACT).is_file():
            return parent / CONTRACT.parent
    return None


class OrigeneratorGalleryContract(unittest.TestCase):
    def setUp(self):
        self.origenerator = _origenerator_beside_this()
        if self.origenerator is None:
            self.skipTest(f"no {CONTRACT.as_posix()} beside this checkout")
        self.promise = json.loads(
            (self.origenerator / origenerator_gallery.PUBLISHED).read_text(encoding="utf-8"))

    def test_the_command_for_origenerators_work_while_closed_is_read_as_it_promises_it(self):
        """Until the Origenerator beside this one publishes the command, there is
        nothing to read, and the stage that runs it does nothing."""
        promised = self.promise.get("downtime_command")
        read = origenerator_gallery.downtime_command(self.origenerator)

        self.assertEqual(read, None if promised is None else tuple(promised))

    def test_every_column_read_here_is_one_origenerator_promises(self):
        """A column this repo selects and that repo does not promise is a
        ``SELECT`` that raises on the next run."""
        promised = {*self.promise["columns"], *self.promise["optional_columns"]}
        read = {
            *origenerator_metadata.COLUMNS,
            origenerator_metadata.OWN_PROVENANCE,
            *withdrawn.COLUMNS,
            origenerator_gallery.REMADE_AT,
            *(lane.unsent_column for lane in lanes.sent_lanes()),
        }

        self.assertLessEqual(read, promised)

    def test_the_lane_stamps_read_here_are_the_ones_origenerator_writes(self):
        """A withdrawal is stamped there and answered here; the two names are
        the whole of what passes back."""
        promised = {lane: stamps["unsent"]
                    for lane, stamps in self.promise["lanes"].items()}

        self.assertEqual(
            {lane.key: lane.unsent_column for lane in lanes.sent_lanes()}, promised)

    def test_the_soundless_copy_role_read_here_is_the_one_origenerator_writes(self):
        self.assertEqual(withdrawn.SILENT_COPY_ROLE, self.promise["silent_copy_role"])

    def test_the_model_keys_read_here_are_the_ones_origenerator_records(self):
        """A run's model is named under one of these inside ``params_json``."""
        self.assertEqual(list(origenerator_metadata.MODEL_KEYS),
                         self.promise["params_model_keys"])

    def test_the_rate_its_videos_are_generated_at_is_read_where_origenerator_publishes_it(self):
        self.assertIsNotNone(origenerator_gallery.generated_fps(self.origenerator))

    def test_the_database_is_where_origenerator_says_it_keeps_it(self):
        """This repo resolves that checkout through its own overlay, so what has
        to agree is the path INSIDE it."""
        relative = Path(self.promise["database_path"])

        self.assertEqual(config.ORIGENERATOR_DB_PATH,
                         config.ORIGENERATOR_PROJECT_DIR / relative)


if __name__ == "__main__":
    unittest.main()
