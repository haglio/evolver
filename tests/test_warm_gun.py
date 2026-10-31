"""Warm Gun's journal: the phone's viewing, and where each line's video is here."""
from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from pathlib import Path

from app_support.flick_folder import flat_flicks_in

from tests.temp_helpers import override_config, touch_video, workspace_temp_dir
from util import warm_gun
from util.warm_gun import Event


@contextmanager
def _genaus_flicks_folder():
    with workspace_temp_dir() as root:
        flicks = root / "genau" / "flicks"
        flat_flicks_in(flicks).mkdir(parents=True)
        with override_config(GENAU_DIR=flicks.parent):
            yield flicks


def _journal(path: Path, lines: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join((json.dumps(line) if not isinstance(line, str) else line) + "\n" for line in lines),
        encoding="utf-8",
    )
    return path


class TestReadJournals(unittest.TestCase):
    def test_reads_every_journal_by_name_each_in_time_order(self):
        with workspace_temp_dir() as root:
            _journal(root / "a.jsonl", [
                {"t": 20, "event": "skip", "path": "1_sorted/provider2/portrait/b.mp4"},
                {"t": 10, "event": "completion", "path": "1_sorted/provider2/portrait/a.mp4"},
            ])
            _journal(root / "b.jsonl", [{"t": 15, "event": "lock", "path": "genau/clips/loop.mp4"}])

            assert warm_gun.read_journals([root]) == {"a.jsonl": [Event(10, "completion", "1_sorted/provider2/portrait/a.mp4"), Event(20, "skip", "1_sorted/provider2/portrait/b.mp4")], "b.jsonl": [Event(15, "lock", "genau/clips/loop.mp4")]}

    def test_a_line_twice_in_a_journal_counts_once(self):
        """The phone re-uploading its whole history must not double every count."""
        with workspace_temp_dir() as root:
            line = {"t": 10, "event": "completion", "path": "1_sorted/provider2/portrait/a.mp4"}
            _journal(root / "phone.jsonl", [line, line])

            assert len(warm_gun.read_journals([root])["phone.jsonl"]) == 1

    def test_the_same_journal_reached_through_two_folders_is_one_journal(self):
        with workspace_temp_dir() as root:
            line = {"t": 10, "event": "completion", "path": "1_sorted/provider2/portrait/a.mp4"}
            _journal(root / "library" / "phone.jsonl", [line])
            _journal(root / "outbox" / "phone.jsonl", [line])

            assert warm_gun.read_journals([root / "library", root / "outbox"]) == {"phone.jsonl": [Event(10, "completion", "1_sorted/provider2/portrait/a.mp4")]}

    def test_a_line_that_is_not_a_record_is_skipped(self):
        with workspace_temp_dir() as root:
            _journal(root / "a.jsonl", [
                "{not json",
                {"t": "soon", "event": "skip", "path": "x.mp4"},
                {"event": "skip", "path": "x.mp4"},
                {"t": 3, "event": "skip", "path": ""},
                "[1, 2]",
                {"t": 4, "event": "skip", "path": "1_sorted/provider2/portrait/a.mp4"},
            ])

            assert warm_gun.read_journals([root]) == {"a.jsonl": [Event(4, "skip", "1_sorted/provider2/portrait/a.mp4")]}

    def test_no_folder_means_no_journals(self):
        with workspace_temp_dir() as root:
            assert warm_gun.read_journals([root / "absent"]) == {}


class TestLibraryVideo(unittest.TestCase):
    def test_a_sorted_clip_is_the_upscale_fun_time_plays(self):
        with override_config(OUT_UPSCALED_DIR=Path("C:/lib/AI/2_outbox/upscaled_by_orientation")):
            assert warm_gun.library_video("1_sorted/provider2/portrait/clip a.mp4") == Path("C:/lib/AI/2_outbox/upscaled_by_orientation/portrait/provider2/clip a_topaz.mp4")

    def test_a_non_ai_video_sits_under_the_non_ai_root(self):
        with override_config(NON_AI_DIR=Path("C:/lib/2D/non_AI")):
            assert warm_gun.library_video("non_AI/bucket/scenes/scene one.mp4") == Path("C:/lib/2D/non_AI/bucket/scenes/scene one.mp4")

    def test_a_delivered_flick_sits_in_genaus_folder(self):
        with _genaus_flicks_folder() as flicks:
            assert warm_gun.library_video(r"genau\flicks\flick_topaz.mp4") == flicks / "flick_topaz.mp4"

    def test_a_flick_in_genaus_folders_sits_at_that_place_under_them(self):
        with _genaus_flicks_folder() as flicks:
            assert warm_gun.library_video("genau/flicks/2D/AI/flick_topaz.mp4") == flicks / "2D" / "AI" / "flick_topaz.mp4"

    def test_a_flick_the_phone_files_under_its_own_name_for_genaus_folder_is_found_in_it(self):
        with _genaus_flicks_folder() as flicks:
            assert warm_gun.library_video("genau/clips/2D/AI/flick_topaz.mp4") == flicks / "2D" / "AI" / "flick_topaz.mp4"

    def test_a_flick_the_phone_named_before_genaus_folders_split_is_found_where_it_went(self):
        with _genaus_flicks_folder() as flicks:
            moved = touch_video(flicks / "2D" / "AI" / "flick_topaz.mp4")

            assert warm_gun.library_video("genau/clips/flick_topaz.mp4") == moved

    def test_a_flick_is_nobody_s_while_no_folder_in_genaus_has_their_shape(self):
        with workspace_temp_dir() as root, override_config(GENAU_DIR=root / "genau"):
            assert warm_gun.library_video("genau/clips/2D/AI/flick_topaz.mp4") is None

    def test_an_upscale_another_app_names_by_its_place_under_the_library_is_that_upscale(self):
        with override_config(LIBRARY_ROOT=Path("C:/lib"),
                             OUT_UPSCALED_DIR=Path("C:/lib/AI/2_outbox/upscaled_by_orientation")):
            assert warm_gun.library_video("AI/2_outbox/upscaled_by_orientation/portrait/provider2/clip a_topaz.mp4") == Path("C:/lib/AI/2_outbox/upscaled_by_orientation/portrait/provider2/clip a_topaz.mp4")

    def test_a_lane_this_library_has_no_folder_for_is_nobody_s(self):
        for path in ("VR/finished/scene.mp4", "1_sorted/short.mp4", "genau/audio/track.mp4", "non_AI", ""):
            with self.subTest(path=path):
                assert warm_gun.library_video(path) is None


class TestPlayedVideo(unittest.TestCase):
    def test_a_sorted_clip_is_streamed_from_1_sorted_itself(self):
        with override_config(SORTED_DIR=Path("C:/lib/AI/1_sorted")):
            assert warm_gun.played_video("1_sorted/provider2/portrait/clip a.mp4") == Path("C:/lib/AI/1_sorted/provider2/portrait/clip a.mp4")

    def test_every_other_lane_is_played_where_it_is(self):
        with _genaus_flicks_folder() as flicks:
            assert warm_gun.played_video("genau/flicks/flick.mp4") == flicks / "flick.mp4"
        assert warm_gun.played_video("VR/scene.mp4") is None
