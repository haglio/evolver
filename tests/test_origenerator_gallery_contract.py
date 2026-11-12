from __future__ import annotations

import json
import unittest
from pathlib import Path

import config
from tasks import origenerator_commands, prompt_scrape, unsent_videos
from util import lanes, origenerator_gallery

CONTRACT = Path("origenerator") / origenerator_gallery.PUBLISHED


def _origenerator_on_disk_beside_this_checkout() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / CONTRACT).is_file():
            return parent / CONTRACT.parent
    return None


class OrigeneratorGalleryContract(unittest.TestCase):
    def setUp(self):
        self.origenerator = _origenerator_on_disk_beside_this_checkout()
        if self.origenerator is None:
            self.skipTest(f"no {CONTRACT.as_posix()} beside this checkout")
        self.promise = json.loads(
            (self.origenerator / origenerator_gallery.PUBLISHED).read_text(encoding="utf-8"))

    def test_the_command_for_origenerators_work_while_closed_is_read_as_it_promises_it(self):
        promised = self.promise.get(origenerator_commands.DOWNTIME)
        read = origenerator_commands.published_command(
            self.origenerator, origenerator_commands.DOWNTIME)

        assert read == (None if promised is None else tuple(promised))

    def test_the_command_that_writes_gallery_entries_is_read_as_it_promises_it(self):
        promised = self.promise.get(origenerator_commands.GALLERY_ENTRIES)
        read = origenerator_commands.published_command(
            self.origenerator, origenerator_commands.GALLERY_ENTRIES)

        assert read == (None if promised is None else tuple(promised))

    def test_the_command_that_takes_the_ai_videos_records_is_read_as_it_promises_it(self):
        promised = self.promise.get(origenerator_commands.RECORDS)
        read = origenerator_commands.published_command(
            self.origenerator, origenerator_commands.RECORDS)

        assert read == (None if promised is None else tuple(promised))

    def test_the_workflow_names_telling_how_a_site_made_a_video_are_read_as_it_publishes_them(self):
        promised = self.promise.get(origenerator_gallery.WORKFLOW_PREFIXES)
        read = origenerator_gallery.workflow_prefixes(self.origenerator)

        assert read == (None if promised is None else origenerator_gallery.WorkflowPrefixes(
            promised["text_to_video"], promised["image_to_video"]))

    def test_every_column_read_here_is_one_origenerator_promises(self):
        promised = {*self.promise["columns"], *self.promise["optional_columns"]}
        read = {
            *prompt_scrape.GALLERY_COLUMNS,
            *unsent_videos.COLUMNS,
            origenerator_gallery.REMADE_AT,
            *(lane.unsent_column for lane in lanes.sent_lanes()),
        }

        assert read <= promised

    def test_the_lane_stamps_read_here_are_the_ones_origenerator_writes(self):
        promised = {lane: (stamps["sent"], stamps["unsent"])
                    for lane, stamps in self.promise["lanes"].items()}

        assert {lane.key: lane.stamps for lane in lanes.sent_lanes()} == promised

    def test_the_soundless_copy_role_read_here_is_the_one_origenerator_writes(self):
        assert self.promise["silent_copy_role"] == unsent_videos.SILENT_COPY_ROLE

    def test_the_rate_its_videos_are_generated_at_is_read_where_origenerator_publishes_it(self):
        assert origenerator_gallery.generated_fps(self.origenerator) is not None

    def test_the_database_s_path_inside_origenerator_s_checkout_is_the_one_it_publishes(self):
        relative = Path(self.promise["database_path"])

        assert config.ORIGENERATOR_PROJECT_DIR / relative == config.ORIGENERATOR_DB_PATH


if __name__ == "__main__":
    unittest.main()
