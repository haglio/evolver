from __future__ import annotations

from pathlib import Path

from app_support.video_names import strip_processing_suffixes

from tasks import origenerator_metadata as om
from util import sidecar
from util.library_records import FRAME_OF_VIDEO_BLOCK, SOURCE_IMAGE_BLOCK


def run(records_folder: Path, *, apply: bool, db_path=None) -> dict[str, int]:
    rows = om.load_rows(db_path)
    owed = written = 0
    for path in sorted(records_folder.rglob("*.json")):
        video = _video_owed(path, rows)
        if video is None:
            continue
        owed += 1
        if apply:
            sidecar.update(path, _gaining(video))
            written += 1
    return {"records_owed": owed, "records_written": written}


def _video_owed(path: Path, rows: list[dict]) -> dict | None:
    image = sidecar.read(path).get(SOURCE_IMAGE_BLOCK)
    if not isinstance(image, dict) or FRAME_OF_VIDEO_BLOCK in image:
        return None
    row = om.video_row_named(f"{strip_processing_suffixes(path.stem)}.mp4", rows)
    block = om.source_image_block_of(row, rows) if row is not None else {}
    video = block.pop(FRAME_OF_VIDEO_BLOCK, None)
    return video if video and block.items() <= image.items() else None


def _gaining(video: dict):
    def change(record: dict) -> dict:
        record[SOURCE_IMAGE_BLOCK][FRAME_OF_VIDEO_BLOCK] = video
        return record
    return change
