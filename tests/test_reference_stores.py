from __future__ import annotations

import json
import unittest
from pathlib import Path

import pytest

from tests.temp_helpers import override_config, workspace_temp_dir
from util import reference_stores


def _only(temp: Path, **used) -> list[reference_stores.ReferenceStore]:
    unused = temp / "no-such-store"
    with override_config(**{
        "GENAUMACHER_SESSIONS_DIR": unused,
        "SCRIPTURE_SESSIONS_DIR": unused,
        "FUN_TIME_WATCH_STATS_FILE": unused / "watch_stats.json",
        "NON_AI_DIR": unused / "non_AI",
        "METADATA_DIR": unused / "metadata",
        **used,
    }):
        return list(reference_stores.discover())


def _a_session(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps({"version": 1, "video_path": "videos/scene one.mp4",
                                "fps": 30, "total_frames": 900}), encoding="utf-8")
    return path


class TestAStoreOfFrameNumbers(unittest.TestCase):
    def test_keeps_to_the_exact_video_its_frames_were_counted_in(self):
        with workspace_temp_dir() as temp:
            _a_session(temp / "genau", "session.json")
            _a_session(temp / "scripture", "project.scripture")

            stores = _only(temp, GENAUMACHER_SESSIONS_DIR=temp / "genau",
                           SCRIPTURE_SESSIONS_DIR=temp / "scripture")

        assert [(store.label, store.any_version_will_do) for store in stores] == [
            ("Genaumacher session", False), ("scripture project", False)]


class TestRewritingAnotherAppsStore(unittest.TestCase):
    def test_a_store_that_cannot_be_read_stops_the_rewrite_rather_than_being_replaced(self):
        with workspace_temp_dir() as temp:
            counts = temp / "watch_stats.json"
            counts.write_text("{not json", encoding="utf-8")
            [store] = _only(temp, FUN_TIME_WATCH_STATS_FILE=counts)

            with pytest.raises(json.JSONDecodeError):
                store.rewrite({"videos/scene one.mp4": "videos/scene two.mp4"})

            assert counts.read_text(encoding="utf-8") == "{not json"

    def test_a_rewritten_store_keeps_the_bare_newlines_its_own_app_writes(self):
        with workspace_temp_dir() as temp:
            session = _a_session(temp / "genau", "session.json")
            [store] = _only(temp, GENAUMACHER_SESSIONS_DIR=temp / "genau")

            store.rewrite({"videos/scene one.mp4": "videos/scene two.mp4"})

            assert b"\r\n" not in session.read_bytes()
            assert json.loads(session.read_text(encoding="utf-8"))["video_path"] == "videos/scene two.mp4"


if __name__ == "__main__":
    unittest.main()
