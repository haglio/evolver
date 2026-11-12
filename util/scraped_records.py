from __future__ import annotations

from pathlib import Path

from app_support.json_store import locked_update, read_json_or_empty

from util.media_files import path_key

_RECORDS = "records"
_FAILED = "failed"


class ScrapedRecords:
    def __init__(self, file: Path) -> None:
        self._file = file

    def staged(self, upscale: Path) -> dict | None:
        entry = self._section(_RECORDS).get(path_key(upscale))
        return None if entry is None else entry["record"]

    def waiting(self) -> list[tuple[Path, dict]]:
        return [(Path(entry["upscale"]), entry["record"])
                for entry in self._section(_RECORDS).values()]

    def stage(self, upscale: Path, record: dict) -> None:
        self._change(_RECORDS, path_key(upscale), {"upscale": str(upscale), "record": record})

    def drop(self, upscale: Path) -> None:
        self._change(_RECORDS, path_key(upscale), None)

    def failed(self, upscale: Path) -> bool:
        return path_key(upscale) in self._section(_FAILED)

    def mark_failed(self, upscale: Path, video: Path, error: BaseException) -> None:
        self._change(_FAILED, path_key(upscale), f"{video.name}\n{error}")

    def _section(self, name: str) -> dict:
        section = read_json_or_empty(self._file).get(name)
        return section if isinstance(section, dict) else {}

    def _change(self, name: str, key: str, value: object) -> None:
        def changed(current: dict) -> dict:
            section = dict(current.get(name) or {})
            if value is None:
                section.pop(key, None)
            else:
                section[key] = value
            return {**current, name: section}

        locked_update(self._file, changed)
