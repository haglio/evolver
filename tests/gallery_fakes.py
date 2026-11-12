from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app_support.gallery_rows import VideoRows

from tasks.origenerator_commands import Handed

TAKEN = Handed(done=1, no_row=0)


class FakeGallery:
    def __init__(self, answer: Handed | None = TAKEN) -> None:
        self.answer = answer
        self.records: list[tuple[Path, dict]] = []
        self.watched_totals: list[dict[Path, dict]] = []
        self.stars: list[tuple[Path, bool]] = []
        self.upscales: list[tuple[Path, dict]] = []

    def record(self, video: Path, record: dict) -> Handed | None:
        self.records.append((video, record))
        return self.answer

    def watched(self, totals: dict[Path, dict]) -> Handed | None:
        self.watched_totals.append(dict(totals))
        return self.answer

    def favorite(self, video: Path, starred: bool) -> Handed | None:
        self.stars.append((video, starred))
        return self.answer

    def upscaled(self, video: Path, provenance: dict) -> Handed | None:
        self.upscales.append((video, provenance))
        return self.answer


def a_gallery_of(path: Path, rows: list[dict]) -> Path:
    columns = sorted({"prompt_id", "output_files", *(name for row in rows for name in row)})
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE generations ({', '.join(f'{name} TEXT' for name in columns)})")
    for row in rows:
        conn.execute(f"INSERT INTO generations ({', '.join(row)}) VALUES "
                     f"({', '.join('?' for _ in row)})", tuple(row.values()))
    conn.commit()
    conn.close()
    return path


def kept_at(prompt_id: str, video: Path, **columns) -> dict:
    return {"prompt_id": prompt_id,
            "output_files": json.dumps([{"filename": video.name, "library_path": str(video)}]),
            **columns}


class GalleryOnDisk(FakeGallery):
    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self._db_path = db_path

    def upscaled(self, video: Path, provenance: dict) -> Handed | None:
        super().upscaled(video, provenance)
        conn = sqlite3.connect(self._db_path)
        try:
            columns = {column[1] for column in conn.execute("PRAGMA table_info(generations)")}
            if "upscale_provenance" not in columns:
                conn.execute("ALTER TABLE generations ADD COLUMN upscale_provenance TEXT")
            rows = [dict(zip(("prompt_id", "output_files"), row, strict=True))
                    for row in conn.execute("SELECT prompt_id, output_files FROM generations")]
            prompt_id = VideoRows(rows)(video)
            if prompt_id is None:
                return Handed(done=0, no_row=1)
            conn.execute("UPDATE generations SET upscale_provenance = ? WHERE prompt_id = ?",
                         (json.dumps(provenance), prompt_id))
            conn.commit()
        finally:
            conn.close()
        return self.answer
