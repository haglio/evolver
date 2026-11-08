from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from pathlib import Path

import pytest
from app_support import video_ids
from app_support.favorites import is_favorite, mark

from tasks import watch_weights
from tests.temp_helpers import (
    LaneLibrary,
    a_drive_that_is_not_there,
    touch_video,
    workspace_temp_dir,
    write_sidecar,
)
from util import sidecar


class _Setting(LaneLibrary):
    def __init__(self, root: Path):
        super().__init__(root)
        self.root = root
        self.journal_dir = root / "app_data" / "warm_gun"
        self.phones_own_folder = a_drive_that_is_not_there() / "WarmGun"
        self.fun_time = root / "fun_time"
        self.stats = self.fun_time / "state" / "watch_stats.json"
        self.cursor = root / "local" / "warm_gun_favorites.json"
        self.fun_time.mkdir(parents=True, exist_ok=True)

    def config(self, **extra):
        return super().config(**{
            "WARM_GUN_JOURNAL_DIRS": (self.journal_dir,),
            "WARM_GUN_OUTBOX": None,
            "FUN_TIME_WATCH_STATS_FILE": self.stats,
            "WARM_GUN_FAVORITES_CURSOR_FILE": self.cursor,
            "LIBRARY_ROOT": self.root,
            **extra,
        })

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


def _favorite(video: Path) -> bool:
    return is_favorite(sidecar.read(sidecar.sidecar_path(video)))


class TestCounts(unittest.TestCase):
    def test_fun_time_s_counts_land_on_the_sidecar_with_their_weight(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.fun_time_counts(a=(upscale, {"completions": 3, "skips": 0, "locks": 0}))

            result = watch_weights.run()

            assert _watch(upscale) == {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}
        assert result.stamped == 1

    def test_fun_time_s_counts_kept_under_the_video_s_id_land_on_its_sidecar(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.stats.parent.mkdir(parents=True)
            s.stats.write_text(json.dumps({
                video_ids.id_of(sidecar.sidecar_path(upscale)): {"completions": 3, "skips": 0, "locks": 0},
            }), encoding="utf-8")

            watch_weights.run()

            assert _watch(upscale) == {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}

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

            assert _watch(upscale) == {"completions": 3, "skips": 0, "locks": 1, "weight": 4.0}

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

            assert _watch(loop)["weight"] == 0.5
            assert _watch(scene)["weight"] == pytest.approx(2 ** (1 / 3), abs=5e-8)

    def test_what_the_sidecar_already_records_is_kept(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            path = sidecar.sidecar_path(upscale)
            write_sidecar(path, {"video": {"type": "short", "action": "Alpha"}})
            s.journal((10, "lock", "1_sorted/provider2/portrait/clip_a.mp4"))

            watch_weights.run()

            assert sidecar.read(path)["video"] == {"type": "short", "action": "Alpha"}

    def test_a_sidecar_already_saying_so_is_left_alone(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "lock", "1_sorted/provider2/portrait/clip_a.mp4"))
            watch_weights.run()
            before = sidecar.sidecar_path(upscale).stat().st_mtime_ns

            result = watch_weights.run()

            assert sidecar.sidecar_path(upscale).stat().st_mtime_ns == before
        assert result.stamped == 0

    def test_a_video_nobody_watches_any_more_loses_its_block(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            path = sidecar.sidecar_path(upscale)
            write_sidecar(path, {"video": {"type": "short"},
                                 "watch": {"completions": 1, "skips": 0, "locks": 0, "weight": 1.26}})

            watch_weights.run()

            assert sidecar.read(path) == {"video": {"type": "short"}}

    def test_a_journal_line_naming_no_video_here_is_counted_and_nothing_else_happens(self):
        with _setting() as s:
            s.journal((10, "completion", "VR/finished/scene.mp4"))

            result = watch_weights.run()

        assert (result.unmapped, result.stamped) == (1, 0)


class TestThePhonesFolderCannotBeReached(unittest.TestCase):
    def test_every_weight_is_left_as_it_was(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            path = sidecar.sidecar_path(upscale)
            stamped = write_sidecar(path, {"watch": {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}})

            with s.config(WARM_GUN_OUTBOX=s.phones_own_folder):
                result = watch_weights.run()

            assert sidecar.read(path) == stamped
        assert result.stamped == 0

    def test_no_favorite_is_carried_and_none_is_skipped_for_good(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((20, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            with s.config(WARM_GUN_OUTBOX=s.phones_own_folder):
                result = watch_weights.run()

            assert not _favorite(upscale)
            assert not s.cursor.exists()
        assert result.favorites_added == 0

    def test_a_folder_gone_from_a_drive_that_is_there_holds_nothing_back(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "lock", "1_sorted/provider2/portrait/clip_a.mp4"))

            with s.config(WARM_GUN_OUTBOX=s.journal_dir.parent / "retired_outbox"):
                result = watch_weights.run()

            assert _watch(upscale)["locks"] == 1
        assert result.stamped == 1

    def test_the_log_says_which_folder_could_not_be_reached(self):
        with (
            _setting() as s,
            s.config(WARM_GUN_OUTBOX=s.phones_own_folder),
            self.assertLogs("tasks.watch_weights", level="WARNING") as logged,
        ):
            watch_weights.run()

        assert logged.output == [f"WARNING:tasks.watch_weights:Watch weights and the phone's favorites left as they were: {s.phones_own_folder} cannot be reached."]


class TestFavorites(unittest.TestCase):
    def test_a_favorite_on_the_phone_marks_its_videos_record(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            result = watch_weights.run()

            assert _favorite(upscale)
        assert result.favorites_added == 1

    def test_an_unfavorite_on_the_phone_takes_the_mark_off(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            write_sidecar(sidecar.sidecar_path(upscale), {"video": {"type": "short"}, "favorite": True})
            s.journal((10, "unfavorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            result = watch_weights.run()

            assert "favorite" not in sidecar.read(sidecar.sidecar_path(upscale))
        assert result.favorites_removed == 1

    def test_a_second_journal_s_older_favorite_lands_after_the_first_s_newer_one(self):
        with _setting() as s:
            _, upscale_a = s.sorted_clip("clip_a")
            _, upscale_b = s.sorted_clip("clip_b")
            s.journal((20, "favorite", "1_sorted/provider2/portrait/clip_b.mp4"))
            watch_weights.run()
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"), name="laptop.jsonl")

            result = watch_weights.run()

            assert _favorite(upscale_a)
            assert _favorite(upscale_b)
        assert result.favorites_added == 1

    def test_the_cursor_a_single_journal_left_behind_speaks_for_the_phone_s_file_only(self):
        with _setting() as s:
            _, upscale_a = s.sorted_clip("clip_a")
            _, upscale_b = s.sorted_clip("clip_b")
            s.cursor.parent.mkdir(parents=True, exist_ok=True)
            s.cursor.write_text(json.dumps({"applied_through": 20}), encoding="utf-8")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_b.mp4"), name="warm-gun-journal.jsonl")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"), name="warm-gun-journal-mac.jsonl")

            result = watch_weights.run()

            assert (_favorite(upscale_a), _favorite(upscale_b)) == (True, False)
            assert json.loads(s.cursor.read_text(encoding="utf-8")) == {"applied_through": {"warm-gun-journal.jsonl": 20, "warm-gun-journal-mac.jsonl": 10}}
        assert result.favorites_added == 1

    def test_a_phone_favorite_is_applied_once_so_fun_time_can_undo_it(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))
            watch_weights.run()
            mark(sidecar.sidecar_path(upscale), False)

            result = watch_weights.run()

            assert not _favorite(upscale)
        assert result.favorites_added == 0

    def test_a_phone_favorite_for_a_video_not_here_yet_is_left_for_a_later_run(self):
        with _setting() as s:
            touch_video(s.sorted_dir / "provider2" / "portrait" / "clip_a.mp4")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            watch_weights.run()
            assert not _favorite(s.outbox / "portrait" / "provider2" / "clip_a_topaz.mp4")
            _, upscale = s.sorted_clip("clip_a")
            watch_weights.run()

            assert _favorite(upscale)

    def test_a_phone_favorite_for_a_video_that_is_gone_holds_nothing_back(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal(
                (10, "favorite", "1_sorted/provider2/portrait/purged.mp4"),
                (20, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"),
            )

            first = watch_weights.run()
            again = watch_weights.run()

            assert _favorite(upscale)
        assert (first.favorites_added, again.favorites_added) == (1, 0)

    def test_a_favorite_fun_time_marked_stays_marked_through_the_stamping(self):
        with _setting() as s:
            loved = touch_video(s.non_ai / "alpha" / "loved.mp4")
            other = touch_video(s.non_ai / "alpha" / "other.mp4")
            mark(sidecar.sidecar_path(loved), True, page="https://example.com/gallery/101")
            s.fun_time_counts(loved=(loved, {"completions": 3}), other=(other, {"completions": 3}))

            watch_weights.run()

            loved_record = sidecar.read(sidecar.sidecar_path(loved))
            assert (loved_record["favorite"], loved_record["web_url"]) == (True, "https://example.com/gallery/101")
            assert "watch" in loved_record
            assert not _favorite(other)

    def test_the_phone_s_favorites_are_marked_where_fun_time_is_not_installed(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))
            s.fun_time.rmdir()

            result = watch_weights.run()

            assert _favorite(upscale)
        assert result.favorites_added == 1


class TestTellingOrigeneratorsGallery(unittest.TestCase):
    def test_the_gallery_is_told_once_the_records_say_what_this_run_carried(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))
            seen = []

            def tell_the_gallery() -> bool:
                seen.append(is_favorite(sidecar.read(sidecar.sidecar_path(upscale))))
                return True

            result = watch_weights.run(tell_the_gallery=tell_the_gallery)

        assert seen == [True]
        assert result.ok

    def test_a_gallery_that_could_not_be_told_fails_the_stage(self):
        with _setting():
            result = watch_weights.run(tell_the_gallery=lambda: False)

        assert not result.ok

    def test_the_gallery_is_told_what_the_records_hold_though_the_phones_folder_cannot_be_reached(
            self):
        told = []
        with _setting() as s, s.config(WARM_GUN_OUTBOX=s.phones_own_folder):
            watch_weights.run(tell_the_gallery=lambda: told.append(True) or True)

        assert told == [True]
