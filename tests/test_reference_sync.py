from __future__ import annotations

import dataclasses
import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tasks import reference_sync
from tests.temp_helpers import override_config, workspace_temp_dir
from util import reference_stores


def _write_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@contextmanager
def _stores_under(temp: Path, **used):
    """Point every store at *temp*, then let the test name the ones it uses.

    Listing them all matters: a store left at its real location gets read — and
    rewritten — out of the live suite by whichever test forgot it. Add each new
    store here as it is registered.
    """
    unused = temp / "no-such-store"
    with override_config(
        VIDEO_SEARCH_ROOT=temp / "videos",
        **{
            "CLIPPER_SESSIONS_DIR": unused,
            "SCRIPTURE_SESSIONS_DIR": unused,
            "FUN_TIME_WATCH_STATS_FILE": unused / "watch_stats.json",
            "FUN_TIME_FAVS_FILE": unused / "favs.csv",
            **used,
        },
    ):
        yield


class TestClipperSessions(unittest.TestCase):
    def test_repoints_a_session_at_the_video_that_moved(self):
        with workspace_temp_dir() as temp:
            moved_to = _write_video(temp / "videos" / "2D" / "non_AI" / "other" / "clip.mp4")
            session = _write_json(
                temp / "sessions" / "Clip.json",
                {"session_name": "Clip", "video_path": str(temp / "videos" / "2D" / "other" / "clip.mp4")},
            )

            with _stores_under(temp, CLIPPER_SESSIONS_DIR=temp / "sessions"):
                result = reference_sync.run()

            payload = json.loads(session.read_text(encoding="utf-8"))
            self.assertEqual(payload["video_path"], str(moved_to))
            self.assertEqual(result.relocated, 1)

    def test_follows_a_video_that_was_renamed_where_it_stood(self):
        """No name left to match on — but the session records the footage's shape."""
        with workspace_temp_dir() as temp:
            folder = temp / "videos" / "larkin" / "0 unsorted"
            renamed_to = _write_video(folder / "Clip_topaz.mp4")
            session = _write_json(
                temp / "sessions" / "Clip.json",
                {"video_path": str(folder / "clip-1080p_60fps.mp4"), "fps": 60.0, "total_frames": 70296},
            )

            with (
                _stores_under(temp, CLIPPER_SESSIONS_DIR=temp / "sessions"),
                patch("util.video_locator.ffprobe.frame_fingerprint", lambda _: (60.0, 70296)),
            ):
                result = reference_sync.run()

            self.assertEqual(json.loads(session.read_text(encoding="utf-8"))["video_path"], str(renamed_to))
            self.assertEqual(result.relocated, 1)

    def test_leaves_a_session_alone_when_the_video_is_nowhere(self):
        with workspace_temp_dir() as temp:
            (temp / "videos").mkdir()
            gone = str(temp / "Downloads" / "scratch.mp4")
            session = _write_json(temp / "sessions" / "Scratch.json", {"video_path": gone})

            with _stores_under(temp, CLIPPER_SESSIONS_DIR=temp / "sessions"):
                with self.assertLogs("tasks.reference_sync", level="WARNING") as logged:
                    result = reference_sync.run()

            self.assertEqual(json.loads(session.read_text(encoding="utf-8"))["video_path"], gone)
            self.assertEqual(result.unresolved, 1)
            # The stage no longer carries the paths on its result, so the log is
            # the only place that says *which* reference could not be followed.
            self.assertIn(gone, logged.records[0].getMessage())

    def test_leaves_a_session_whose_video_never_moved_untouched(self):
        with workspace_temp_dir() as temp:
            still_there = _write_video(temp / "videos" / "clip.mp4")
            session = _write_json(temp / "sessions" / "Clip.json", {"video_path": str(still_there)})
            written_at = session.stat().st_mtime_ns

            with _stores_under(temp, CLIPPER_SESSIONS_DIR=temp / "sessions"):
                result = reference_sync.run()

            self.assertEqual(session.stat().st_mtime_ns, written_at)
            self.assertEqual((result.relocated, result.unresolved), (0, 0))


class TestScriptureProjects(unittest.TestCase):
    def test_repoints_a_project_at_the_video_that_moved(self):
        with workspace_temp_dir() as temp:
            moved_to = _write_video(temp / "videos" / "non_AI" / "larkin" / "clip.mp4")
            project = _write_json(
                temp / "projects" / "Clip.scripture",
                {
                    "video_path": str(temp / "videos" / "larkin" / "clip.mp4").replace("\\", "/"),
                    "splits": [12, 340],
                },
            )

            with _stores_under(temp, SCRIPTURE_SESSIONS_DIR=temp / "projects"):
                reference_sync.run()

            payload = json.loads(project.read_text(encoding="utf-8"))
            self.assertEqual(payload["video_path"], str(moved_to))
            self.assertEqual(payload["splits"], [12, 340])


class TestWatchStats(unittest.TestCase):
    def test_carries_a_video_s_watch_counts_over_to_its_new_path(self):
        with workspace_temp_dir() as temp:
            moved_to = _write_video(temp / "videos" / "non_AI" / "other" / "clip.mp4")
            stayed = _write_video(temp / "videos" / "stayed.mp4")
            stats = _write_json(
                temp / "state" / "watch_stats.json",
                {
                    str(temp / "videos" / "other" / "clip.mp4").lower(): {"completions": 9, "skips": 1, "locks": 2},
                    str(stayed).lower(): {"completions": 1, "skips": 0, "locks": 0},
                },
            )

            with _stores_under(temp, FUN_TIME_WATCH_STATS_FILE=stats):
                reference_sync.run()

            payload = json.loads(stats.read_text(encoding="utf-8"))
            self.assertEqual(payload[str(moved_to).lower()], {"completions": 9, "skips": 1, "locks": 2})
            self.assertEqual(payload[str(stayed).lower()], {"completions": 1, "skips": 0, "locks": 0})


class TestFunTimeFavorites(unittest.TestCase):
    def _favs_csv(self, path: Path, was_at: Path) -> Path:
        url = "file:///" + str(was_at).replace("\\", "/")
        path.write_text(
            "local_file,web_url\n"
            f'"=HYPERLINK(""{url}"";""{was_at}"")",https://example.test/clip\n',
            encoding="utf-8",
        )
        return path

    def test_repoints_a_favorite_at_the_video_that_moved(self):
        with workspace_temp_dir() as temp:
            moved_to = _write_video(temp / "videos" / "non_AI" / "other" / "clip.mp4")
            favs = self._favs_csv(temp / "favs.csv", temp / "videos" / "other" / "clip.mp4")

            with _stores_under(temp, FUN_TIME_FAVS_FILE=favs):
                reference_sync.run()

            cell = favs.read_text(encoding="utf-8").splitlines()[1]
            self.assertIn("file:///" + str(moved_to).replace("\\", "/"), cell)
            self.assertIn(str(moved_to), cell)
            self.assertIn("https://example.test/clip", cell)


if __name__ == "__main__":
    unittest.main()


class TestUnwritableStore(unittest.TestCase):
    def test_a_store_that_cannot_be_rewritten_is_counted_and_the_rest_are_followed(self):
        """One unwritable file must not abort the stage, and must not pass as ok.

        The stores are other apps' files, and one of them open in the app that
        owns it is an ordinary Tuesday -- so a failed rewrite is news about that
        store, not the end of the run.
        """
        with workspace_temp_dir() as temp:
            moved_to = _write_video(temp / "videos" / "2D" / "non_AI" / "other" / "clip.mp4")
            was_at = temp / "videos" / "2D" / "other" / "clip.mp4"
            locked = _write_json(
                temp / "sessions" / "Locked.json",
                {"session_name": "Locked", "video_path": str(was_at)},
            )
            writable = _write_json(
                temp / "sessions" / "Writable.json",
                {"session_name": "Writable", "video_path": str(was_at)},
            )
            real_rewrite = reference_stores._rewrite_video_path_field

            def refuse_the_locked_one(path: Path, moves: dict[str, str]) -> None:
                if path == locked:
                    raise OSError("the app that owns it has it open")
                real_rewrite(path, moves)

            patched = patch.object(
                reference_stores, "_rewrite_video_path_field", refuse_the_locked_one
            )
            with _stores_under(temp, CLIPPER_SESSIONS_DIR=temp / "sessions"), patched:
                result = reference_sync.run()

            self.assertEqual(result.write_errors, 1)
            self.assertFalse(result.ok)
            self.assertEqual(result.relocated, 1)
            self.assertEqual(
                json.loads(writable.read_text(encoding="utf-8"))["video_path"],
                str(moved_to),
            )
            self.assertEqual(
                json.loads(locked.read_text(encoding="utf-8"))["video_path"],
                str(was_at),
            )


class TestReferenceStoreSurface(unittest.TestCase):
    """A store asks its own file, rather than being handed it back.

    Every call site read `store.read(store.path)`, `store.rewrite(store.path,
    moves)`, `store.fingerprint(store.path)` -- the object passing its own
    field into its own function, three times out of three, with nothing
    stopping a caller passing a different one.
    """

    def _store(self, calls):
        return reference_stores.ReferenceStore(
            "example",
            Path("C:/somewhere/refs.json"),
            lambda path: calls.append(("read", path)) or ["a.mp4"],
            lambda path, moves: calls.append(("rewrite", path, moves)),
            lambda path: calls.append(("fingerprint", path)) or (30.0, 100),
        )

    def test_all_three_reach_the_stores_own_path(self):
        calls = []
        store = self._store(calls)

        self.assertEqual(store.read(), ["a.mp4"])
        store.rewrite({"a.mp4": "b.mp4"})
        self.assertEqual(store.fingerprint(), (30.0, 100))

        self.assertEqual(
            calls,
            [
                ("read", store.path),
                ("rewrite", store.path, {"a.mp4": "b.mp4"}),
                ("fingerprint", store.path),
            ],
        )

    def test_a_store_that_records_no_fingerprint_answers_none(self):
        """Most of them record only a path, so a renamed video is beyond their
        reach and the last-resort match is skipped rather than guessed."""
        store = reference_stores.ReferenceStore(
            "example", Path("C:/somewhere/refs.json"), lambda path: [],
            lambda path, moves: None,
        )

        self.assertIsNone(store.fingerprint())


class TestAShapeThisStageWasNotWrittenFor(unittest.TestCase):
    """Each of these files belongs to a repo that never hears about this one, so
    a format it changes arrives here as a file that still parses and still looks
    rewritable. Rewriting one blind is how this app corrupts another's saved
    work, and the reference it would have followed is stranded either way -- so
    the file is left exactly as it is and somebody is told."""

    def test_a_session_stamped_with_a_version_this_stage_does_not_know_is_left_alone(self):
        with workspace_temp_dir() as temp:
            _write_video(temp / "videos" / "2D" / "other" / "moved" / "clip.mp4")
            was_at = str(temp / "videos" / "2D" / "other" / "clip.mp4")
            session = _write_json(
                temp / "sessions" / "Clip.json",
                {"version": 2, "session_name": "Clip", "video_path": was_at},
            )

            with _stores_under(temp, CLIPPER_SESSIONS_DIR=temp / "sessions"):
                result = reference_sync.run()

            self.assertEqual(json.loads(session.read_text(encoding="utf-8"))["video_path"], was_at)
            self.assertEqual(result.refused, 1)
            self.assertEqual(result.relocated, 0)
            self.assertTrue(result.needs_an_eye)
            self.assertTrue(result.ok)

    def test_a_session_written_before_the_stamp_existed_is_the_first_version(self):
        """Every session and project on disk today was written without one."""
        with workspace_temp_dir() as temp:
            moved_to = _write_video(temp / "videos" / "2D" / "other" / "moved" / "clip.mp4")
            session = _write_json(
                temp / "sessions" / "Clip.json",
                {"session_name": "Clip",
                 "video_path": str(temp / "videos" / "2D" / "other" / "clip.mp4")},
            )

            with _stores_under(temp, CLIPPER_SESSIONS_DIR=temp / "sessions"):
                result = reference_sync.run()

            self.assertEqual(
                json.loads(session.read_text(encoding="utf-8"))["video_path"], str(moved_to))
            self.assertEqual(result.refused, 0)

    def test_a_project_stamped_with_a_version_this_stage_does_not_know_is_left_alone(self):
        with workspace_temp_dir() as temp:
            _write_video(temp / "videos" / "2D" / "other" / "moved" / "clip.mp4")
            was_at = str(temp / "videos" / "2D" / "other" / "clip.mp4")
            project = _write_json(
                temp / "projects" / "Clip.scripture", {"version": 7, "video_path": was_at})

            with _stores_under(temp, SCRIPTURE_SESSIONS_DIR=temp / "projects"):
                result = reference_sync.run()

            self.assertEqual(json.loads(project.read_text(encoding="utf-8"))["video_path"], was_at)
            self.assertEqual(result.refused, 1)

    def test_watch_counts_that_are_not_counts_are_left_alone(self):
        """These carry no version and cannot: every key there is a video path.
        Their shape is the contract instead."""
        with workspace_temp_dir() as temp:
            _write_video(temp / "videos" / "non_AI" / "other" / "clip.mp4")
            was_at = str(temp / "videos" / "other" / "clip.mp4").lower()
            stats = _write_json(temp / "state" / "watch_stats.json", {was_at: 9})

            with _stores_under(temp, FUN_TIME_WATCH_STATS_FILE=stats):
                result = reference_sync.run()

            self.assertEqual(json.loads(stats.read_text(encoding="utf-8")), {was_at: 9})
            self.assertEqual(result.refused, 1)

    def test_a_favorites_file_with_no_local_path_column_is_left_alone(self):
        """The header row is this one's version, and a rewrite without that
        column silently repoints nothing at all."""
        with workspace_temp_dir() as temp:
            _write_video(temp / "videos" / "non_AI" / "other" / "clip.mp4")
            favs = temp / "favs.csv"
            favs.write_text("web_url\nhttps://example.test/clip\n", encoding="utf-8")
            before = favs.read_text(encoding="utf-8")

            with _stores_under(temp, FUN_TIME_FAVS_FILE=favs):
                result = reference_sync.run()

            self.assertEqual(favs.read_text(encoding="utf-8"), before)
            self.assertEqual(result.refused, 1)


class TestReferenceSyncResultSurface(unittest.TestCase):
    def test_the_result_carries_only_what_a_reader_consults(self):
        """Every field lands in a run record; one nothing reads is dead weight."""
        self.assertEqual(
            {f.name for f in dataclasses.fields(reference_sync.ReferenceSyncResult)},
            {"checked", "relocated", "unresolved", "write_errors", "refused"},
        )
