import json
import unittest
from pathlib import Path

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


class TestClipperSessions(unittest.TestCase):
    def test_repoints_a_session_at_the_video_that_moved(self):
        with workspace_temp_dir() as temp:
            moved_to = _write_video(temp / "videos" / "2D" / "non_AI" / "other" / "clip.mp4")
            session = _write_json(
                temp / "sessions" / "Clip.json",
                {"session_name": "Clip", "video_path": str(temp / "videos" / "2D" / "other" / "clip.mp4")},
            )

            with override_config(
                VIDEO_SEARCH_ROOT=temp / "videos",
                CLIPPER_SESSIONS_DIR=temp / "sessions",
            ):
                result = reference_sync.run()

            payload = json.loads(session.read_text(encoding="utf-8"))
            self.assertEqual(payload["video_path"], str(moved_to))
            self.assertEqual(result.relocated, 1)

    def test_leaves_a_session_alone_when_the_video_is_nowhere(self):
        with workspace_temp_dir() as temp:
            (temp / "videos").mkdir()
            gone = str(temp / "Downloads" / "scratch.mp4")
            session = _write_json(temp / "sessions" / "Scratch.json", {"video_path": gone})

            with override_config(
                VIDEO_SEARCH_ROOT=temp / "videos",
                CLIPPER_SESSIONS_DIR=temp / "sessions",
            ):
                result = reference_sync.run()

            self.assertEqual(json.loads(session.read_text(encoding="utf-8"))["video_path"], gone)
            self.assertEqual(result.unresolved_paths, [gone])

    def test_leaves_a_session_whose_video_never_moved_untouched(self):
        with workspace_temp_dir() as temp:
            still_there = _write_video(temp / "videos" / "clip.mp4")
            session = _write_json(temp / "sessions" / "Clip.json", {"video_path": str(still_there)})
            written_at = session.stat().st_mtime_ns

            with override_config(
                VIDEO_SEARCH_ROOT=temp / "videos",
                CLIPPER_SESSIONS_DIR=temp / "sessions",
            ):
                result = reference_sync.run()

            self.assertEqual(session.stat().st_mtime_ns, written_at)
            self.assertEqual((result.relocated, result.unresolved), (0, 0))


if __name__ == "__main__":
    unittest.main()
