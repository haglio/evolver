from __future__ import annotations

import json
import unittest
from pathlib import Path

import config
from tasks import origenerator_metadata, taken_back
from util import lanes, origenerator_gallery

CONTRACT = Path("origenerator") / origenerator_gallery.PUBLISHED


def _origenerator_beside_this() -> Path | None:
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
        promised = self.promise.get("downtime_command")
        read = origenerator_gallery.downtime_command(self.origenerator)

        assert read == (None if promised is None else tuple(promised))

    def test_every_column_read_here_is_one_origenerator_promises(self):
        promised = {*self.promise["columns"], *self.promise["optional_columns"]}
        read = {
            *origenerator_metadata.COLUMNS,
            origenerator_metadata.OWN_PROVENANCE,
            *taken_back.COLUMNS,
            origenerator_gallery.REMADE_AT,
            *(lane.unsent_column for lane in lanes.sent_lanes()),
        }

        assert read <= promised

    def test_the_lane_stamps_read_here_are_the_ones_origenerator_writes(self):
        promised = {lane: stamps["unsent"]
                    for lane, stamps in self.promise["lanes"].items()}

        assert {lane.key: lane.unsent_column for lane in lanes.sent_lanes()} == promised

    def test_the_soundless_copy_role_read_here_is_the_one_origenerator_writes(self):
        assert self.promise["silent_copy_role"] == taken_back.SILENT_COPY_ROLE

    def test_the_model_keys_read_here_are_the_ones_origenerator_records(self):
        assert list(origenerator_metadata.MODEL_KEYS) == self.promise["params_model_keys"]

    def test_the_rate_its_videos_are_generated_at_is_read_where_origenerator_publishes_it(self):
        assert origenerator_gallery.generated_fps(self.origenerator) is not None

    def test_the_database_is_where_origenerator_says_it_keeps_it(self):
        relative = Path(self.promise["database_path"])

        assert config.ORIGENERATOR_PROJECT_DIR / relative == config.ORIGENERATOR_DB_PATH


if __name__ == "__main__":
    unittest.main()
