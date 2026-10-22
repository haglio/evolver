"""The stage that puts both apps' viewing on every sidecar, and passes favorites both ways."""
from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from pathlib import Path

from tasks import watch_weights
from tests.temp_helpers import (
    LaneLibrary,
    a_drive_that_is_not_there,
    touch_video,
    workspace_temp_dir,
    write_sidecar,
)
from util import favs_csv, sidecar


class _Setting(LaneLibrary):
    """A lane library plus the phone's journal folder and Fun Time's files."""

    def __init__(self, root: Path):
        super().__init__(root)
        self.root = root
        self.journal_dir = root / "app_data" / "warm_gun"
        self.phones_own_folder = a_drive_that_is_not_there() / "WarmGun"
        self.fun_time = root / "fun_time"
        self.stats = self.fun_time / "state" / "watch_stats.json"
        self.favs = self.fun_time / "favs.csv"
        self.cursor = root / "local" / "warm_gun_favorites.json"
        self.acts_cursor = root / "local" / "picked_acts.json"
        self.fun_time.mkdir(parents=True, exist_ok=True)

    def config(self, **extra):
        return super().config(**{
            "WARM_GUN_JOURNAL_DIRS": (self.journal_dir,),
            "WARM_GUN_OUTBOX": None,
            "FUN_TIME_WATCH_STATS_FILE": self.stats,
            "FUN_TIME_FAVS_FILE": self.favs,
            "WARM_GUN_FAVORITES_CURSOR_FILE": self.cursor,
            "PICKED_ACTS_CURSOR_FILE": self.acts_cursor,
            "LIBRARY_ROOT": self.root,
            **extra,
        })

    def journal(self, *lines: tuple[int, str, str], name: str = "phone.jsonl") -> None:
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        (self.journal_dir / name).write_text(
            "".join(json.dumps({"t": t, "event": event, "path": path}) + "\n" for t, event, path in lines),
            encoding="utf-8",
        )

    def pick_act(self, t: int, video: Path, act: str) -> None:
        """A line Origenerator writes when an act is picked on a video's Action row."""
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        line = {"t": t, "event": "action", "path": video.relative_to(self.root).as_posix(),
                "action": act}
        with (self.journal_dir / "origenerator.jsonl").open("a", encoding="utf-8") as journal:
            journal.write(json.dumps(line) + "\n")

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
            loop = touch_video(s.genau_flicks / "loop.mp4")
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
            write_sidecar(path, {"video": {"type": "short", "action": "Alpha"}})
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
            write_sidecar(path, {"video": {"type": "short"},
                                 "watch": {"completions": 1, "skips": 0, "locks": 0, "weight": 1.26}})

            watch_weights.run()

            self.assertEqual(sidecar.read(path), {"video": {"type": "short"}})

    def test_a_journal_line_naming_no_video_here_is_counted_and_nothing_else_happens(self):
        with _setting() as s:
            s.journal((10, "completion", "VR/finished/scene.mp4"))

            result = watch_weights.run()

        self.assertEqual((result.unmapped, result.stamped), (1, 0))


class TestThePhonesFolderCannotBeReached(unittest.TestCase):
    def test_every_weight_is_left_as_it_was(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            path = sidecar.sidecar_path(upscale)
            stamped = write_sidecar(path, {"watch": {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}})

            with s.config(WARM_GUN_OUTBOX=s.phones_own_folder):
                result = watch_weights.run()

            self.assertEqual(sidecar.read(path), stamped)
        self.assertEqual(result.stamped, 0)

    def test_no_favorite_is_carried_and_none_is_skipped_for_good(self):
        with _setting() as s:
            s.sorted_clip("clip_a")
            s.journal((20, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            with s.config(WARM_GUN_OUTBOX=s.phones_own_folder):
                result = watch_weights.run()

            self.assertFalse(s.favs.exists())
            self.assertFalse(s.cursor.exists())
        self.assertEqual(result.favorites_added, 0)

    def test_a_folder_gone_from_a_drive_that_is_there_holds_nothing_back(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "lock", "1_sorted/provider2/portrait/clip_a.mp4"))

            with s.config(WARM_GUN_OUTBOX=s.journal_dir.parent / "retired_outbox"):
                result = watch_weights.run()

            self.assertEqual(_watch(upscale)["locks"], 1)
        self.assertEqual(result.stamped, 1)

    def test_the_log_says_which_folder_could_not_be_reached(self):
        with _setting() as s:
            with s.config(WARM_GUN_OUTBOX=s.phones_own_folder):
                with self.assertLogs("tasks.watch_weights", level="WARNING") as logged:
                    watch_weights.run()

        self.assertEqual(logged.output, [
            ("WARNING:tasks.watch_weights:Watch weights and the phone's favorites left as they "
             f"were: {s.phones_own_folder} cannot be reached.")])


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
            write_sidecar(sidecar.sidecar_path(upscale), {"video": {"type": "short"}, "favorite": True})
            s.journal((10, "unfavorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            result = watch_weights.run()

            self.assertEqual(favs_csv.favorite_videos(s.favs), [])
            self.assertNotIn("favorite", sidecar.read(sidecar.sidecar_path(upscale)))
        self.assertEqual(result.favorites_removed, 1)

    def test_a_second_journal_s_older_favorite_lands_after_the_first_s_newer_one(self):
        """Two machines upload two files into the one folder, and one of them
        can arrive late: a laptop is quit from the front as often as not, so
        its favorite made at ten can reach the folder after the phone's made
        at twenty has already been applied."""
        with _setting() as s:
            _, upscale_a = s.sorted_clip("clip_a")
            _, upscale_b = s.sorted_clip("clip_b")
            s.journal((20, "favorite", "1_sorted/provider2/portrait/clip_b.mp4"))
            watch_weights.run()
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"), name="laptop.jsonl")

            result = watch_weights.run()

            self.assertEqual(set(favs_csv.favorite_videos(s.favs)), {upscale_a, upscale_b})
        self.assertEqual(result.favorites_added, 1)

    def test_the_cursor_a_single_journal_left_behind_speaks_for_the_phone_s_file_only(self):
        """Before the laptop there was one journal and one time; that time was
        reached through the phone's file alone, so it holds that file back and
        no other."""
        with _setting() as s:
            _, upscale_a = s.sorted_clip("clip_a")
            s.sorted_clip("clip_b")
            s.cursor.parent.mkdir(parents=True, exist_ok=True)
            s.cursor.write_text(json.dumps({"applied_through": 20}), encoding="utf-8")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_b.mp4"), name="warm-gun-journal.jsonl")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"), name="warm-gun-journal-mac.jsonl")

            result = watch_weights.run()

            self.assertEqual(favs_csv.favorite_videos(s.favs), [upscale_a])
            self.assertEqual(json.loads(s.cursor.read_text(encoding="utf-8")), {
                "applied_through": {"warm-gun-journal.jsonl": 20, "warm-gun-journal-mac.jsonl": 10},
            })
        self.assertEqual(result.favorites_added, 1)

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


class TestActsPickedInOrigenerator(unittest.TestCase):
    def test_a_picked_act_is_written_into_the_videos_record(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.pick_act(10, upscale, "Act Beta")

            watch_weights.run()

            self.assertEqual(sidecar.action_of(sidecar.read(sidecar.sidecar_path(upscale))),
                             "Act Beta")

    def test_a_pick_is_written_once_so_fun_time_can_strike_it_out_after(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.pick_act(10, upscale, "Act Beta")
            watch_weights.run()
            write_sidecar(sidecar.sidecar_path(upscale), {"video": {"wrong_action": "Act Beta"}})

            watch_weights.run()

            self.assertEqual(sidecar.action_of(sidecar.read(sidecar.sidecar_path(upscale))), "")

    def test_the_last_of_two_picks_is_the_act_the_record_keeps(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.pick_act(10, upscale, "Act Beta")
            s.pick_act(20, upscale, "Act Gamma")

            result = watch_weights.run()

            self.assertEqual(sidecar.action_of(sidecar.read(sidecar.sidecar_path(upscale))),
                             "Act Gamma")
        self.assertEqual(result.acts_named, 2)
