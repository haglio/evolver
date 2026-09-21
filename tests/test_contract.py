"""The document this repo publishes about its pipeline, held against the config.

Origenerator hands clips to this pipeline by copying a file into one folder and
reads the upscale back out of another, and it cannot import this repo -- so it
had both paths and the half-written-file marker written out on its own side.
Renaming a folder here left it dropping clips where nothing ingests them, with
both suites green.

``evolver_contract.json`` at the checkout root is how those names travel now.
These hold the document to what this repo actually reads and writes.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import config
from tests.temp_helpers import workspace_temp_dir
from util import contract, media_files, sidecar, video_type, watch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


class PublishedDocument(unittest.TestCase):
    def test_the_tracked_copy_is_what_publishing_writes(self):
        """Run ``util.contract.publish()`` when this fails: a document
        that has drifted from this module tells a sender something untrue."""
        tracked = contract.contract_path(REPO_ROOT)

        with workspace_temp_dir() as root:
            self.assertEqual(contract.publish(root).read_text(encoding="utf-8"),
                             tracked.read_text(encoding="utf-8"))

    def test_each_folder_it_names_is_the_one_this_repo_uses(self):
        """Library-relative, because the library root is private and the two
        apps resolve it from their own overlays."""
        document = _document()

        self.assertEqual(
            {name: config.BASE_DIR / Path(value)
             for name, value in document["library_relative"].items()},
            {"inbox_dir": config.INBOX_DIR,
             "upscaled_dir": config.OUT_UPSCALED_DIR},
        )

    def test_a_name_carrying_the_marker_is_one_this_repo_refuses_to_ingest(self):
        """The whole point of the marker: a copy still being written must not be
        read as a finished video."""
        marker = _document()["partial_marker"]

        self.assertTrue(media_files.is_partial_path(Path(f"a-clip{marker}mp4")))
        self.assertFalse(media_files.is_partial_path(Path("a-clip.mp4")))


if __name__ == "__main__":
    unittest.main()


class TheLibraryRecord(unittest.TestCase):
    """What a reader of a library video's record may rely on.

    Fun Time reads one on every clip it shows and writes one field back, and
    both sides spelled every name for themselves until this document existed.
    """

    def setUp(self):
        self.record = _document()["library_record"]

    def test_every_kind_it_names_is_one_this_repo_records(self):
        """A reader branching on the kind has to know the whole set."""
        self.assertEqual(self.record["video_kinds"], list(video_type.TYPES))

    def test_the_field_the_reader_writes_is_the_one_this_repo_clears(self):
        """Fun Time strikes an act out and leaves this in its place; only the
        backfill tool clears it, once a viewer has finally named the act."""
        video = self.record["blocks"][video_type.BLOCK]

        self.assertEqual(video["written_by_the_reader"], [sidecar.WRONG_ACTION_FIELD])
        self.assertIn(sidecar.WRONG_ACTION_FIELD, video["fields"])

    def test_the_watch_block_it_names_is_the_one_this_repo_stamps(self):
        """The counts and the weight a shuffled playlist draws by."""
        stamped = watch.stamped({}, dict.fromkeys(watch.COUNT_FIELDS, 1), favorite=True)

        self.assertEqual(sorted(stamped[watch.BLOCK]),
                         sorted(self.record["blocks"][watch.BLOCK]["fields"]))
        self.assertIn(watch.FAVORITE_FIELD, self.record["top_level_keys"])

    def test_the_kind_and_the_running_time_sit_where_it_says(self):
        """Both go in the video block, which is where a reader looks for them."""
        stamped = video_type.timed(video_type.stamped({}, video_type.SHORT), 12.5)

        self.assertEqual(sorted(stamped[video_type.BLOCK]),
                         sorted((video_type.FIELD, video_type.DURATION_FIELD)))
        declared = self.record["blocks"][video_type.BLOCK]["fields"]
        self.assertLessEqual({video_type.FIELD, video_type.DURATION_FIELD},
                             set(declared))
