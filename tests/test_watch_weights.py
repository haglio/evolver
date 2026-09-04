"""The stage that puts both apps' viewing on every sidecar, and passes favorites both ways."""

import json
import unittest
from contextlib import contextmanager
from pathlib import Path

from tasks import watch_weights
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir
from util import favs_csv, sidecar


class _Setting(LaneLibrary):
    """A lane library plus the phone's journal folder and Fun Time's files."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.journal_dir = root / "videos" / "warm_gun"
        self.fun_time = root / "fun_time"
        self.stats = self.fun_time / "state" / "watch_stats.json"
        self.favs = self.fun_time / "favs.csv"
        self.cursor = root / "local" / "warm_gun_favorites.json"
        self.fun_time.mkdir(parents=True, exist_ok=True)

    def config(self, **extra):
        return super().config(
            WARM_GUN_JOURNAL_DIRS=(self.journal_dir,),
            FUN_TIME_WATCH_STATS_FILE=self.stats,
            FUN_TIME_FAVS_FILE=self.favs,
            WARM_GUN_FAVORITES_CURSOR_FILE=self.cursor,
            **extra,
        )

    def journal(self, *lines: tuple[int, str, str], name: str = "phone.jsonl") -> None:
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        (self.journal_dir / name).write_text(
            "".join(json.dumps({"t": t, "event": event, "path": path}) + "\n" for t, event, path in lines),
            encoding="utf-8",
        )

    def fun_time_counts(self, **counts_by_video: tuple[Path, dict]) -> None:
        self.stats.parent.mkdir(parents=True, exist_ok=True)
        self.stats.write_text(
            json.dumps({str(video).lower(): counts for video, counts in counts_by_video.values()}),
            encoding="utf-8",
        )

    def sorted_clip(self, name: str) -> tuple[Path, Path]:
        """A generated clip and its upscale, both on disk."""
        video = touch_video(self.sorted_dir / "provider2" / "portrait" / f"{name}.mp4")
        upscale = touch_video(self.outbox / "portrait" / "provider2" / f"{name}_topaz.mp4")
        return video, upscale


@contextmanager
def _setting():
    with workspace_temp_dir() as root:
        setting = _Setting(root)
        with setting.config():
            yield setting


def _watch(video: Path) -> dict | None:
    return sidecar.read(sidecar.sidecar_path(video)).get("watch")


class TestCounts(unittest.TestCase):
    def test_fun_time_s_counts_land_on_the_sidecar_with_their_weight(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.fun_time_counts(a=(upscale, {"completions": 3, "skips": 0, "locks": 0}))

            result = watch_weights.run()

            self.assertEqual(_watch(upscale), {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0})
        self.assertEqual(result.stamped, 1)

    def test_the_phone_s_viewing_is_added_to_fun_time_s(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.fun_time_counts(a=(upscale, {"completions": 1}))
            s.journal(
                (10, "completion", "1_sorted/provider2/portrait/clip_a.mp4"),
                (20, "completion", "1_sorted/provider2/portrait/clip_a.mp4"),
                (30, "lock", "1_sorted/provider2/portrait/clip_a.mp4"),
            )

            watch_weights.run()

            self.assertEqual(_watch(upscale), {"completions": 3, "skips": 0, "locks": 1, "weight": 4.0})

    def test_a_delivered_loop_and_a_scene_are_stamped_by_their_own_lanes(self):
        with _setting() as s:
            loop = touch_video(s.genau_clips / "loop.mp4")
            scene = touch_video(s.non_ai / "alpha" / "scene one.mp4")
            s.journal(
                (10, "skip", "genau/clips/loop.mp4"),
                (11, "skip", "genau/clips/loop.mp4"),
                (12, "skip", "genau/clips/loop.mp4"),
                (13, "completion", "non_AI/alpha/scene one.mp4"),
            )

            watch_weights.run()

            self.assertEqual(_watch(loop)["weight"], 0.5)
            self.assertAlmostEqual(_watch(scene)["weight"], 2 ** (1 / 3))

    def test_what_the_sidecar_already_records_is_kept(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            path = sidecar.sidecar_path(upscale)
            sidecar.write(path, {"video": {"type": "short", "action": "Alpha"}})
            s.journal((10, "lock", "1_sorted/provider2/portrait/clip_a.mp4"))

            watch_weights.run()

            self.assertEqual(sidecar.read(path)["video"], {"type": "short", "action": "Alpha"})

    def test_a_sidecar_already_saying_so_is_left_alone(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "lock", "1_sorted/provider2/portrait/clip_a.mp4"))
            watch_weights.run()
            before = sidecar.sidecar_path(upscale).stat().st_mtime_ns

            result = watch_weights.run()

            self.assertEqual(sidecar.sidecar_path(upscale).stat().st_mtime_ns, before)
        self.assertEqual(result.stamped, 0)

    def test_a_video_nobody_watches_any_more_loses_its_block(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            path = sidecar.sidecar_path(upscale)
            sidecar.write(path, {"video": {"type": "short"},
                                 "watch": {"completions": 1, "skips": 0, "locks": 0, "weight": 1.26}})

            watch_weights.run()

            self.assertEqual(sidecar.read(path), {"video": {"type": "short"}})

    def test_a_journal_line_naming_no_video_here_is_counted_and_nothing_else_happens(self):
        with _setting() as s:
            s.journal((10, "completion", "VR/finished/scene.mp4"))

            result = watch_weights.run()

        self.assertEqual((result.unmapped, result.stamped), (1, 0))


class TestFavorites(unittest.TestCase):
    def test_a_favorite_on_the_phone_joins_fun_time_s_favorites_and_is_flagged(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            result = watch_weights.run()

            self.assertEqual(favs_csv.favorite_videos(s.favs), [upscale])
            self.assertIs(sidecar.read(sidecar.sidecar_path(upscale)).get("favorite"), True)
        self.assertEqual(result.favorites_added, 1)

    def test_an_unfavorite_on_the_phone_removes_the_row_and_the_flag(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            favs_csv.add_favorite(s.favs, upscale)
            sidecar.write(sidecar.sidecar_path(upscale), {"video": {"type": "short"}, "favorite": True})
            s.journal((10, "unfavorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            result = watch_weights.run()

            self.assertEqual(favs_csv.favorite_videos(s.favs), [])
            self.assertNotIn("favorite", sidecar.read(sidecar.sidecar_path(upscale)))
        self.assertEqual(result.favorites_removed, 1)

    def test_a_phone_favorite_is_applied_once_so_fun_time_can_undo_it(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))
            watch_weights.run()
            favs_csv.remove_favorite(s.favs, upscale)

            result = watch_weights.run()

            self.assertEqual(favs_csv.favorite_videos(s.favs), [])
        self.assertEqual(result.favorites_added, 0)

    def test_a_phone_favorite_for_a_video_not_here_yet_is_left_for_a_later_run(self):
        with _setting() as s:
            touch_video(s.sorted_dir / "provider2" / "portrait" / "clip_a.mp4")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            watch_weights.run()
            self.assertEqual(favs_csv.favorite_videos(s.favs), [])
            _, upscale = s.sorted_clip("clip_a")
            watch_weights.run()

            self.assertEqual(favs_csv.favorite_videos(s.favs), [upscale])

    def test_a_phone_favorite_for_a_video_that_is_gone_holds_nothing_back(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal(
                (10, "favorite", "1_sorted/provider2/portrait/purged.mp4"),
                (20, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"),
            )

            first = watch_weights.run()
            again = watch_weights.run()

            self.assertEqual(favs_csv.favorite_videos(s.favs), [upscale])
        self.assertEqual((first.favorites_added, again.favorites_added), (1, 0))

    def test_fun_time_s_own_favorites_are_flagged_on_their_sidecars(self):
        with _setting() as s:
            loved = touch_video(s.non_ai / "alpha" / "loved.mp4")
            other = touch_video(s.non_ai / "alpha" / "other.mp4")
            favs_csv.add_favorite(s.favs, loved)

            watch_weights.run()

            self.assertIs(sidecar.read(sidecar.sidecar_path(loved)).get("favorite"), True)
            self.assertNotIn("favorite", sidecar.read(sidecar.sidecar_path(other)))

    def test_without_fun_time_installed_the_phone_s_favorites_wait(self):
        with _setting() as s:
            s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))
            s.fun_time.rmdir()

            result = watch_weights.run()

            self.assertFalse(s.favs.exists())
            self.assertFalse(s.cursor.exists())
        self.assertEqual(result.favorites_added, 0)
