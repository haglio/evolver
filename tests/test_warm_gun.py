"""Warm Gun's journal: the phone's viewing, and where each line's video is here."""

import json
import unittest
from pathlib import Path

from tests.temp_helpers import override_config, workspace_temp_dir
from util import warm_gun
from util.warm_gun import Event


def _journal(path: Path, lines: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join((json.dumps(line) if not isinstance(line, str) else line) + "\n" for line in lines),
        encoding="utf-8",
    )
    return path


class TestReadJournal(unittest.TestCase):
    def test_reads_every_line_of_every_journal_in_time_order(self):
        with workspace_temp_dir() as root:
            _journal(root / "a.jsonl", [
                {"t": 20, "event": "skip", "path": "1_sorted/provider2/portrait/b.mp4"},
                {"t": 10, "event": "completion", "path": "1_sorted/provider2/portrait/a.mp4"},
            ])
            _journal(root / "b.jsonl", [{"t": 15, "event": "lock", "path": "genau/clips/loop.mp4"}])

            self.assertEqual(warm_gun.read_journal(root), [
                Event(10, "completion", "1_sorted/provider2/portrait/a.mp4"),
                Event(15, "lock", "genau/clips/loop.mp4"),
                Event(20, "skip", "1_sorted/provider2/portrait/b.mp4"),
            ])

    def test_a_line_present_in_two_journals_counts_once(self):
        """A copy seeded beside the phone's own file, or the phone re-uploading
        its whole history, must not double every count."""
        with workspace_temp_dir() as root:
            line = {"t": 10, "event": "completion", "path": "1_sorted/provider2/portrait/a.mp4"}
            _journal(root / "seeded.jsonl", [line])
            _journal(root / "phone.jsonl", [line, line])

            self.assertEqual(len(warm_gun.read_journal(root)), 1)

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

            self.assertEqual(
                warm_gun.read_journal(root),
                [Event(4, "skip", "1_sorted/provider2/portrait/a.mp4")],
            )

    def test_no_folder_means_no_events(self):
        with workspace_temp_dir() as root:
            self.assertEqual(warm_gun.read_journal(root / "absent"), [])


class TestLibraryVideo(unittest.TestCase):
    def test_a_sorted_clip_is_the_upscale_fun_time_plays(self):
        with override_config(OUT_UPSCALED_DIR=Path("C:/lib/AI/2_outbox/upscaled_by_orientation")):
            self.assertEqual(
                warm_gun.library_video("1_sorted/provider2/portrait/clip a.mp4"),
                Path("C:/lib/AI/2_outbox/upscaled_by_orientation/portrait/provider2/clip a_topaz.mp4"),
            )

    def test_a_non_ai_video_sits_under_the_non_ai_root(self):
        with override_config(NON_AI_DIR=Path("C:/lib/2D/non_AI")):
            self.assertEqual(
                warm_gun.library_video("non_AI/bucket/scenes/scene one.mp4"),
                Path("C:/lib/2D/non_AI/bucket/scenes/scene one.mp4"),
            )

    def test_a_delivered_loop_sits_in_genau_s_folder(self):
        with override_config(GENAU_CLIPS_DIR=Path("C:/lib/genau/clips")):
            self.assertEqual(
                warm_gun.library_video(r"genau\clips\loop_topaz.mp4"),
                Path("C:/lib/genau/clips/loop_topaz.mp4"),
            )

    def test_a_lane_this_library_has_no_folder_for_is_nobody_s(self):
        for path in ("VR/finished/scene.mp4", "1_sorted/short.mp4", "genau/audio/track.mp4", "non_AI", ""):
            with self.subTest(path=path):
                self.assertIsNone(warm_gun.library_video(path))


class TestPlayedVideo(unittest.TestCase):
    def test_a_sorted_clip_is_streamed_from_1_sorted_itself(self):
        with override_config(SORTED_DIR=Path("C:/lib/AI/1_sorted")):
            self.assertEqual(
                warm_gun.played_video("1_sorted/provider2/portrait/clip a.mp4"),
                Path("C:/lib/AI/1_sorted/provider2/portrait/clip a.mp4"),
            )

    def test_every_other_lane_is_played_where_it_is(self):
        with override_config(GENAU_CLIPS_DIR=Path("C:/lib/genau/clips")):
            self.assertEqual(
                warm_gun.played_video("genau/clips/loop.mp4"), Path("C:/lib/genau/clips/loop.mp4")
            )
        self.assertIsNone(warm_gun.played_video("VR/scene.mp4"))
