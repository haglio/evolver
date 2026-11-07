from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_support import favorites
from app_support.mirrored_tree import library_roots_beside, mirrored_path
from shared_ui.orientation import ORIENTATIONS, PORTRAIT

import config
from tests.temp_helpers import workspace_temp_dir
from util import contract, media_files, sidecar, video_kind, warm_gun, watch

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


class PublishedDocument(unittest.TestCase):
    def test_the_tracked_copy_is_what_publishing_writes(self):
        tracked = contract.contract_path(REPO_ROOT)

        with workspace_temp_dir() as root:
            assert contract.publish(root).read_text(encoding="utf-8") == tracked.read_text(encoding="utf-8")

    def test_each_folder_it_names_is_the_one_this_repo_uses(self):
        document = _document()

        assert {name: config.LIBRARY_ROOT / Path(value) for name, value in document["library_relative"].items()} == {"inbox_dir": config.INBOX_DIR, "upscaled_dir": config.OUT_UPSCALED_DIR, "trash_dir": config.TRASH_DIR}

    def test_a_videos_record_is_where_the_mirrored_tree_puts_it_under_the_named_folder(self):
        metadata = config.LIBRARY_ROOT / Path(_document()["library_record"]["folder"])
        video = config.OUT_UPSCALED_DIR / "portrait" / "a-source" / "clip_topaz.mp4"

        assert mirrored_path(video, roots=library_roots_beside(metadata), mirror_root=metadata, suffix=".json") == sidecar.sidecar_path(video)

    def test_a_name_carrying_the_marker_is_one_this_repo_refuses_to_ingest(self):
        marker = _document()["partial_marker"]

        assert media_files.is_partial_path(Path(f"a-clip{marker}mp4"))
        assert not media_files.is_partial_path(Path("a-clip.mp4"))


if __name__ == "__main__":
    unittest.main()


class TheLibraryRecord(unittest.TestCase):
    def setUp(self):
        self.record = _document()["library_record"]

    def test_every_kind_it_names_is_one_this_repo_records(self):
        assert self.record["video_kinds"] == list(video_kind.TYPES)

    def test_the_orientations_it_names_are_the_familys_two_words(self):
        assert self.record["video_orientations"] == list(ORIENTATIONS)

    def test_the_field_the_reader_writes_is_the_one_this_repo_clears(self):
        video = self.record["blocks"][video_kind.BLOCK]

        assert video["written_by_the_reader"] == [sidecar.WRONG_ACTION_FIELD]
        assert sidecar.WRONG_ACTION_FIELD in video["fields"]

    def test_the_watch_block_it_names_is_the_one_this_repo_stamps(self):
        stamped = watch.stamped({}, dict.fromkeys(watch.COUNT_FIELDS, 1))

        assert sorted(stamped[watch.BLOCK]) == sorted(self.record["blocks"][watch.BLOCK]["fields"])

    def test_a_favorite_and_its_page_are_the_ones_the_apps_that_mark_them_write(self):
        both = [favorites.FAVORITE_KEY, favorites.PAGE_KEY]

        assert set(both) <= set(self.record["top_level_keys"])
        assert self.record["top_level_written_by_the_reader"] == both

    def test_the_kind_the_running_time_and_the_orientation_sit_where_it_says(self):
        stamped = video_kind.oriented(
            video_kind.timed(video_kind.stamped({}, video_kind.SHORT), 12.5), PORTRAIT)
        own = {video_kind.FIELD, video_kind.DURATION_FIELD, video_kind.ORIENTATION_FIELD}

        assert set(stamped[video_kind.BLOCK]) == own
        declared = self.record["blocks"][video_kind.BLOCK]["fields"]
        assert own <= set(declared)


class TheJournals(unittest.TestCase):
    def setUp(self):
        self.journals = _document()["journals"]

    def test_a_line_in_the_fields_it_names_is_an_event_the_favorites_stage_applies(self):
        upscale = (config.OUT_UPSCALED_DIR / "portrait" / "a-source" / "clip_topaz.mp4")
        line = dict(zip(self.journals["fields"],
                        (5, "favorite", upscale.relative_to(config.LIBRARY_ROOT).as_posix()),
                        strict=True))

        with workspace_temp_dir() as root:
            (root / "another-app.jsonl").write_text(f"{json.dumps(line)}\n", encoding="utf-8")
            [[event]] = warm_gun.read_journals([root]).values()

        assert event.event in self.journals["favorite_events"]
        assert warm_gun.library_video(event.path) == upscale
