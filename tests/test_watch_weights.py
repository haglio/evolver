from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from pathlib import Path

import pytest
from app_support import video_ids
from app_support.favorites import is_favorite, mark

from tasks import watch_weights
from tests.gallery_fakes import FakeGallery, a_gallery_of, kept_at
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
        self.gallery_db = root / "gallery.db"
        self.fun_time.mkdir(parents=True, exist_ok=True)

    def config(self, **extra):
        return super().config(**{
            "WARM_GUN_JOURNAL_DIRS": (self.journal_dir,),
            "WARM_GUN_OUTBOX": None,
            "FUN_TIME_WATCH_STATS_FILE": self.stats,
            "WARM_GUN_FAVORITES_CURSOR_FILE": self.cursor,
            "LIBRARY_ROOT": self.root,
            "ORIGENERATOR_DB_PATH": self.gallery_db,
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

    def non_ai_scene(self, name: str) -> Path:
        return touch_video(self.non_ai / "alpha" / f"{name}.mp4")

    def sorted_clip(self, name: str) -> tuple[Path, Path]:
        video = touch_video(self.sorted_dir / "provider2" / "portrait" / f"{name}.mp4")
        upscale = touch_video(self.kino_upscales / "portrait" / "provider2" / f"{name}_topaz.mp4")
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


def _counts(completions=0, skips=0, locks=0) -> dict:
    return {"completions": completions, "skips": skips, "locks": locks}


class TestCountsOfAnAiVideo(unittest.TestCase):
    def test_fun_time_s_counts_are_handed_to_the_gallery_and_no_sidecar_is_written(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.fun_time_counts(a=(upscale, {"completions": 3, "skips": 0, "locks": 0}))

            result = watch_weights.run(gallery=gallery)

            assert not sidecar.sidecar_path(upscale).exists()
        assert gallery.watched_totals == [{upscale: _counts(completions=3)}]
        assert result.stamped == 1

    def test_counts_kept_under_its_old_record_id_and_under_its_path_are_added_together(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            a_gallery_of(s.gallery_db, [kept_at("made-1", upscale, library_id="id-one")])
            s.stats.parent.mkdir(parents=True)
            s.stats.write_text(json.dumps({
                "id-one": _counts(completions=3),
                str(upscale).lower(): _counts(skips=1),
            }), encoding="utf-8")

            watch_weights.run(gallery=gallery)

        assert gallery.watched_totals == [{upscale: _counts(completions=3, skips=1)}]

    def test_the_phone_s_viewing_is_added_to_fun_time_s(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.fun_time_counts(a=(upscale, {"completions": 1}))
            s.journal(
                (10, "completion", "1_sorted/provider2/portrait/clip_a.mp4"),
                (20, "completion", "1_sorted/provider2/portrait/clip_a.mp4"),
                (30, "lock", "1_sorted/provider2/portrait/clip_a.mp4"),
            )

            watch_weights.run(gallery=gallery)

        assert gallery.watched_totals == [{upscale: _counts(completions=3, locks=1)}]

    def test_an_ai_genau_flick_is_handed_over_beside_the_kino_videos_in_one_go(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            flick = touch_video(s.genau_flicks / "2D" / "AI" / "loop.mp4")
            s.journal((10, "skip", "genau/clips/2D/AI/loop.mp4"))

            watch_weights.run(gallery=gallery)

            assert not sidecar.sidecar_path(flick).exists()
        assert gallery.watched_totals == [{upscale: _counts(), flick: _counts(skips=1)}]

    def test_an_upscale_not_made_yet_is_not_handed_over(self):
        gallery = FakeGallery()
        with _setting() as s:
            touch_video(s.sorted_dir / "provider2" / "portrait" / "clip_a.mp4")

            watch_weights.run(gallery=gallery)

        assert gallery.watched_totals == [{}]

    def test_a_gallery_that_did_not_take_the_counts_fails_the_stage(self):
        with _setting() as s:
            s.sorted_clip("clip_a")

            result = watch_weights.run(gallery=FakeGallery(None))

        assert (result.ok, result.stamped) == (False, 0)

    def test_a_gallery_that_cannot_be_read_still_takes_the_counts_kept_under_the_path(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.gallery_db.write_bytes(b"not a database, made up for this test")
            s.fun_time_counts(a=(upscale, {"locks": 2}))

            watch_weights.run(gallery=gallery)

        assert gallery.watched_totals == [{upscale: _counts(locks=2)}]


class TestCountsOfANonAiVideo(unittest.TestCase):
    def test_fun_time_s_counts_land_on_the_sidecar_with_their_weight(self):
        with _setting() as s:
            scene = s.non_ai_scene("scene one")
            s.fun_time_counts(a=(scene, {"completions": 3, "skips": 0, "locks": 0}))

            result = watch_weights.run(gallery=FakeGallery())

            assert _watch(scene) == {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}
        assert result.stamped == 1

    def test_fun_time_s_counts_kept_under_the_video_s_id_land_on_its_sidecar(self):
        with _setting() as s:
            scene = s.non_ai_scene("scene one")
            s.stats.parent.mkdir(parents=True)
            s.stats.write_text(json.dumps({
                video_ids.id_of(sidecar.sidecar_path(scene)): {"completions": 3, "skips": 0, "locks": 0},
            }), encoding="utf-8")

            watch_weights.run(gallery=FakeGallery())

            assert _watch(scene) == {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}

    def test_a_loop_genaumacher_cut_and_a_scene_are_stamped_by_their_own_lanes(self):
        gallery = FakeGallery()
        with _setting() as s:
            loop = touch_video(s.genau_flicks / "2D" / "non_AI" / "loop.mp4")
            scene = s.non_ai_scene("scene one")
            s.journal(
                (10, "skip", "genau/clips/2D/non_AI/loop.mp4"),
                (11, "skip", "genau/clips/2D/non_AI/loop.mp4"),
                (12, "skip", "genau/clips/2D/non_AI/loop.mp4"),
                (13, "completion", "non_AI/alpha/scene one.mp4"),
            )

            watch_weights.run(gallery=gallery)

            assert _watch(loop)["weight"] == 0.5
            assert _watch(scene)["weight"] == pytest.approx(2 ** (1 / 3), abs=5e-8)
        assert gallery.watched_totals == []

    def test_what_the_sidecar_already_records_is_kept(self):
        with _setting() as s:
            scene = s.non_ai_scene("scene one")
            path = sidecar.sidecar_path(scene)
            write_sidecar(path, {"video": {"type": "excerpt", "action": "Alpha"}})
            s.journal((10, "lock", "non_AI/alpha/scene one.mp4"))

            watch_weights.run(gallery=FakeGallery())

            assert sidecar.read(path)["video"] == {"type": "excerpt", "action": "Alpha"}

    def test_a_sidecar_already_saying_so_is_left_alone(self):
        with _setting() as s:
            scene = s.non_ai_scene("scene one")
            s.journal((10, "lock", "non_AI/alpha/scene one.mp4"))
            watch_weights.run(gallery=FakeGallery())
            before = sidecar.sidecar_path(scene).stat().st_mtime_ns

            result = watch_weights.run(gallery=FakeGallery())

            assert sidecar.sidecar_path(scene).stat().st_mtime_ns == before
        assert result.stamped == 0

    def test_a_video_nobody_watches_any_more_loses_its_block(self):
        with _setting() as s:
            scene = s.non_ai_scene("scene one")
            path = sidecar.sidecar_path(scene)
            write_sidecar(path, {"video": {"type": "excerpt"},
                                 "watch": {"completions": 1, "skips": 0, "locks": 0, "weight": 1.26}})

            watch_weights.run(gallery=FakeGallery())

            assert sidecar.read(path) == {"video": {"type": "excerpt"}}

    def test_a_journal_line_naming_no_video_here_is_counted_and_nothing_else_happens(self):
        with _setting() as s:
            s.journal((10, "completion", "VR/finished/scene.mp4"))

            result = watch_weights.run(gallery=FakeGallery())

        assert (result.unmapped, result.stamped) == (1, 0)


class TestThePhonesFolderCannotBeReached(unittest.TestCase):
    def test_every_weight_is_left_as_it_was(self):
        gallery = FakeGallery()
        with _setting() as s:
            s.sorted_clip("clip_a")
            scene = s.non_ai_scene("scene one")
            path = sidecar.sidecar_path(scene)
            stamped = write_sidecar(path, {"watch": {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}})

            with s.config(WARM_GUN_OUTBOX=s.phones_own_folder):
                result = watch_weights.run(gallery=gallery)

            assert sidecar.read(path) == stamped
        assert (result.stamped, gallery.watched_totals) == (0, [])

    def test_no_favorite_is_carried_and_none_is_skipped_for_good(self):
        gallery = FakeGallery()
        with _setting() as s:
            s.sorted_clip("clip_a")
            s.journal((20, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            with s.config(WARM_GUN_OUTBOX=s.phones_own_folder):
                result = watch_weights.run(gallery=gallery)

            assert not s.cursor.exists()
        assert (result.favorites_added, gallery.stars) == (0, [])

    def test_a_folder_gone_from_a_drive_that_is_there_holds_nothing_back(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "lock", "1_sorted/provider2/portrait/clip_a.mp4"))

            with s.config(WARM_GUN_OUTBOX=s.journal_dir.parent / "retired_outbox"):
                result = watch_weights.run(gallery=gallery)

        assert gallery.watched_totals == [{upscale: _counts(locks=1)}]
        assert result.stamped == 1

    def test_the_log_says_which_folder_could_not_be_reached(self):
        with (
            _setting() as s,
            s.config(WARM_GUN_OUTBOX=s.phones_own_folder),
            self.assertLogs("tasks.watch_weights", level="WARNING") as logged,
        ):
            watch_weights.run(gallery=FakeGallery())

        assert logged.output == [f"WARNING:tasks.watch_weights:Watch weights and the phone's favorites left as they were: {s.phones_own_folder} cannot be reached."]


class TestFavorites(unittest.TestCase):
    def test_a_favorite_on_the_phone_stars_an_ai_video_in_the_gallery(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            result = watch_weights.run(gallery=gallery)

            assert not sidecar.sidecar_path(upscale).exists()
        assert gallery.stars == [(upscale, True)]
        assert result.favorites_added == 1

    def test_an_unfavorite_on_the_phone_takes_an_ai_video_s_star_off(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "unfavorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            result = watch_weights.run(gallery=gallery)

        assert gallery.stars == [(upscale, False)]
        assert result.favorites_removed == 1

    def test_a_favorite_on_the_phone_marks_a_non_ai_videos_record(self):
        with _setting() as s:
            scene = s.non_ai_scene("scene one")
            s.journal((10, "favorite", "non_AI/alpha/scene one.mp4"))

            result = watch_weights.run(gallery=FakeGallery())

            assert _favorite(scene)
        assert result.favorites_added == 1

    def test_an_unfavorite_on_the_phone_takes_a_non_ai_videos_mark_off(self):
        with _setting() as s:
            scene = s.non_ai_scene("scene one")
            write_sidecar(sidecar.sidecar_path(scene), {"video": {"type": "excerpt"}, "favorite": True})
            s.journal((10, "unfavorite", "non_AI/alpha/scene one.mp4"))

            result = watch_weights.run(gallery=FakeGallery())

            assert "favorite" not in sidecar.read(sidecar.sidecar_path(scene))
        assert result.favorites_removed == 1

    def test_a_second_journal_s_older_favorite_lands_after_the_first_s_newer_one(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale_a = s.sorted_clip("clip_a")
            _, upscale_b = s.sorted_clip("clip_b")
            s.journal((20, "favorite", "1_sorted/provider2/portrait/clip_b.mp4"))
            watch_weights.run(gallery=gallery)
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"), name="laptop.jsonl")

            result = watch_weights.run(gallery=gallery)

        assert gallery.stars == [(upscale_b, True), (upscale_a, True)]
        assert result.favorites_added == 1

    def test_the_cursor_a_single_journal_left_behind_speaks_for_the_phone_s_file_only(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale_a = s.sorted_clip("clip_a")
            s.sorted_clip("clip_b")
            s.cursor.parent.mkdir(parents=True, exist_ok=True)
            s.cursor.write_text(json.dumps({"applied_through": 20}), encoding="utf-8")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_b.mp4"), name="warm-gun-journal.jsonl")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"), name="warm-gun-journal-mac.jsonl")

            result = watch_weights.run(gallery=gallery)

            assert json.loads(s.cursor.read_text(encoding="utf-8")) == {"applied_through": {"warm-gun-journal.jsonl": 20, "warm-gun-journal-mac.jsonl": 10}}
        assert gallery.stars == [(upscale_a, True)]
        assert result.favorites_added == 1

    def test_a_phone_favorite_is_handed_over_once_so_fun_time_can_undo_it(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))
            watch_weights.run(gallery=gallery)

            result = watch_weights.run(gallery=gallery)

        assert gallery.stars == [(upscale, True)]
        assert result.favorites_added == 0

    def test_a_phone_favorite_for_a_video_not_here_yet_is_left_for_a_later_run(self):
        gallery = FakeGallery()
        with _setting() as s:
            touch_video(s.sorted_dir / "provider2" / "portrait" / "clip_a.mp4")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            watch_weights.run(gallery=gallery)
            assert gallery.stars == []
            _, upscale = s.sorted_clip("clip_a")
            watch_weights.run(gallery=gallery)

        assert gallery.stars == [(upscale, True)]

    def test_a_phone_favorite_the_gallery_could_not_take_is_handed_over_on_a_later_run(self):
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))

            refused = watch_weights.run(gallery=FakeGallery(None))
            gallery = FakeGallery()
            taken = watch_weights.run(gallery=gallery)

        assert (refused.favorites_added, taken.favorites_added) == (0, 1)
        assert gallery.stars == [(upscale, True)]

    def test_a_phone_favorite_for_a_video_that_is_gone_holds_nothing_back(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal(
                (10, "favorite", "1_sorted/provider2/portrait/purged.mp4"),
                (20, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"),
            )

            first = watch_weights.run(gallery=gallery)
            again = watch_weights.run(gallery=gallery)

        assert gallery.stars == [(upscale, True)]
        assert (first.favorites_added, again.favorites_added) == (1, 0)

    def test_a_favorite_fun_time_marked_stays_marked_through_the_stamping(self):
        with _setting() as s:
            loved = s.non_ai_scene("loved")
            other = s.non_ai_scene("other")
            mark(sidecar.sidecar_path(loved), True, page="https://example.com/gallery/101")
            s.fun_time_counts(loved=(loved, {"completions": 3}), other=(other, {"completions": 3}))

            watch_weights.run(gallery=FakeGallery())

            loved_record = sidecar.read(sidecar.sidecar_path(loved))
            assert (loved_record["favorite"], loved_record["web_url"]) == (True, "https://example.com/gallery/101")
            assert "watch" in loved_record
            assert not _favorite(other)

    def test_the_phone_s_favorites_are_handed_over_where_fun_time_is_not_installed(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))
            s.fun_time.rmdir()

            result = watch_weights.run(gallery=gallery)

        assert gallery.stars == [(upscale, True)]
        assert result.favorites_added == 1


class TestTellingOrigeneratorsGallery(unittest.TestCase):
    def test_the_gallery_takes_in_its_entries_once_this_run_handed_over_its_stars(self):
        gallery = FakeGallery()
        with _setting() as s:
            _, upscale = s.sorted_clip("clip_a")
            s.journal((10, "favorite", "1_sorted/provider2/portrait/clip_a.mp4"))
            seen = []

            def tell_the_gallery() -> bool:
                seen.append(list(gallery.stars))
                return True

            result = watch_weights.run(tell_the_gallery=tell_the_gallery, gallery=gallery)

        assert seen == [[(upscale, True)]]
        assert result.ok

    def test_a_gallery_that_could_not_be_told_fails_the_stage(self):
        with _setting():
            result = watch_weights.run(tell_the_gallery=lambda: False, gallery=FakeGallery())

        assert not result.ok

    def test_the_gallery_is_told_what_the_records_hold_though_the_phones_folder_cannot_be_reached(
            self):
        told = []
        with _setting() as s, s.config(WARM_GUN_OUTBOX=s.phones_own_folder):
            watch_weights.run(tell_the_gallery=lambda: told.append(True) or True,
                              gallery=FakeGallery())

        assert told == [True]
