import dataclasses
import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from tasks import reference_sync
from tests.temp_helpers import override_config, workspace_temp_dir


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


class TestReferenceSyncResultSurface(unittest.TestCase):
    def test_the_result_carries_only_what_a_reader_consults(self):
        """Every field lands in a run record; one nothing reads is dead weight."""
        self.assertEqual(
            {f.name for f in dataclasses.fields(reference_sync.ReferenceSyncResult)},
            {"checked", "relocated", "unresolved", "write_errors"},
        )
