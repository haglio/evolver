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

from app_support.mirrored_tree import library_roots_beside, mirrored_path
from shared_ui.orientation import ORIENTATIONS, PORTRAIT

import config
from tests.temp_helpers import workspace_temp_dir
from util import contract, media_files, sidecar, video_type, warm_gun, watch

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
            {name: config.LIBRARY_ROOT / Path(value)
             for name, value in document["library_relative"].items()},
            {"inbox_dir": config.INBOX_DIR,
             "upscaled_dir": config.OUT_UPSCALED_DIR},
        )

    def test_a_videos_record_is_where_the_mirrored_tree_puts_it_under_the_named_folder(self):
        metadata = config.LIBRARY_ROOT / Path(_document()["library_record"]["folder"])
        video = config.OUT_UPSCALED_DIR / "portrait" / "a-source" / "clip_topaz.mp4"

        self.assertEqual(
            mirrored_path(video, roots=library_roots_beside(metadata), mirror_root=metadata,
                          suffix=".json"),
            sidecar.sidecar_path(video),
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

    def test_the_orientations_it_names_are_the_familys_two_words(self):
        self.assertEqual(self.record["video_orientations"], list(ORIENTATIONS))

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

    def test_the_kind_the_running_time_and_the_orientation_sit_where_it_says(self):
        """All three go in the video block, which is where a reader looks for them."""
        stamped = video_type.oriented(
            video_type.timed(video_type.stamped({}, video_type.SHORT), 12.5), PORTRAIT)
        own = {video_type.FIELD, video_type.DURATION_FIELD, video_type.ORIENTATION_FIELD}

        self.assertEqual(set(stamped[video_type.BLOCK]), own)
        declared = self.record["blocks"][video_type.BLOCK]["fields"]
        self.assertLessEqual(own, set(declared))


class TheJournals(unittest.TestCase):
    """What another app writes for the favorites stage to carry into Fun Time's
    list, the way the phone's journal is carried."""

    def setUp(self):
        self.journals = _document()["journals"]

    def test_the_folder_it_names_is_the_one_inside_the_library_the_journals_are_read_from(self):
        self.assertEqual(config.LIBRARY_ROOT / Path(self.journals["folder"]),
                         config.WARM_GUN_JOURNAL_DIRS[0])

    def test_a_line_in_the_fields_it_names_is_an_event_the_favorites_stage_applies(self):
        upscale = (config.OUT_UPSCALED_DIR / "portrait" / "a-source" / "clip_topaz.mp4")
        line = dict(zip(self.journals["fields"],
                        (5, "favorite", upscale.relative_to(config.LIBRARY_ROOT).as_posix()),
                        strict=True))

        with workspace_temp_dir() as root:
            (root / "another-app.jsonl").write_text(f"{json.dumps(line)}\n", encoding="utf-8")
            [[event]] = warm_gun.read_journals([root]).values()

        self.assertIn(event.event, self.journals["favorite_events"])
        self.assertEqual(warm_gun.library_video(event.path), upscale)

    def test_a_line_naming_a_picked_act_is_one_the_stage_writes_into_the_record(self):
        upscale = (config.OUT_UPSCALED_DIR / "portrait" / "a-source" / "clip_topaz.mp4")
        line = {**dict(zip(self.journals["fields"],
                           (5, self.journals["act_event"],
                            upscale.relative_to(config.LIBRARY_ROOT).as_posix()),
                           strict=True)),
                self.journals["act_field"]: "Act Beta"}

        with workspace_temp_dir() as root:
            (root / "another-app.jsonl").write_text(f"{json.dumps(line)}\n", encoding="utf-8")
            [[event]] = warm_gun.read_journals([root]).values()

        self.assertEqual((event.event, event.action), (warm_gun.ACT_EVENT, "Act Beta"))
