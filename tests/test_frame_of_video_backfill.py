from __future__ import annotations

import json
import unittest

from tasks import frame_of_video_backfill as backfill
from tests.temp_helpers import workspace_temp_dir
from tests.test_origenerator_metadata import (
    _FRAME,
    _WORDS_VIDEO,
    _ALibrary,
    _record_of,
    _row,
)

_FRAME_BLOCK = {"positive_prompt": "the words of the frame", "seed": "3"}


def _made_row():
    return _row("made-1", params={"input_image": _FRAME}, outputs=["wan22_i2v_00001_.mp4"])


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestBringingRecordsUpToTheVideoTheirFrameCameFrom(unittest.TestCase):
    def test_a_dry_run_counts_and_writes_nothing(self):
        with workspace_temp_dir() as root, _ALibrary(root) as library:
            library.with_rows(*library.t2v_video_and_its_frame(), _made_row())
            record = _record_of(root, "wan22_i2v_00001_", {"source_image": _FRAME_BLOCK})

            counts = backfill.run(root / "metadata", apply=False, db_path=library.db)
            on_disk = _read(record)

        assert counts == {"records_owed": 1, "records_written": 0}
        assert "frame_of_video" not in on_disk["source_image"]

    def test_apply_writes_a_video_and_its_upscale(self):
        with workspace_temp_dir() as root, _ALibrary(root) as library:
            library.with_rows(*library.t2v_video_and_its_frame(), _made_row())
            records = [_record_of(root, name, {"source_image": _FRAME_BLOCK, "favorite": True})
                       for name in ("wan22_i2v_00001_", "wan22_i2v_00001__topaz")]

            counts = backfill.run(root / "metadata", apply=True, db_path=library.db)
            on_disk = [_read(record) for record in records]
            again = backfill.run(root / "metadata", apply=True, db_path=library.db)

        assert counts == {"records_owed": 2, "records_written": 2}
        assert [one["source_image"]["frame_of_video"] for one in on_disk] == [_WORDS_VIDEO] * 2
        assert [one["favorite"] for one in on_disk] == [True, True]
        assert again == {"records_owed": 0, "records_written": 0}

    def test_a_record_of_another_video_with_that_name_is_left_alone(self):
        with workspace_temp_dir() as root, _ALibrary(root) as library:
            library.with_rows(*library.t2v_video_and_its_frame(), _made_row())
            _record_of(root, "wan22_i2v_00001_",
                       {"source_image": {"positive_prompt": "another image", "seed": "9"}})

            counts = backfill.run(root / "metadata", apply=True, db_path=library.db)

        assert counts == {"records_owed": 0, "records_written": 0}

    def test_a_record_no_generation_made_is_left_alone(self):
        with workspace_temp_dir() as root, _ALibrary(root) as library:
            library.with_rows(*library.t2v_video_and_its_frame(), _made_row())
            _record_of(root, "made-elsewhere", {"source_image": _FRAME_BLOCK})

            counts = backfill.run(root / "metadata", apply=False, db_path=library.db)

        assert counts == {"records_owed": 0, "records_written": 0}
