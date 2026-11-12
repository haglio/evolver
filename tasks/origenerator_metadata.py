from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from app_support.comfy_file_refs import frame_name
from app_support.video_names import strip_uniquifier

from util import lanes, origenerator_gallery, provenance
from util.media_files import path_key

COLUMNS = ("prompt_id", "workflow_name", "workflow_version", "output_files")

OWN_PROVENANCE = "provenance"
PUBLISHED_ACTIONS = "combined_labels"


def _library_paths_of(row: dict) -> list[Path]:
    return [Path(file["library_path"]) for file in _row_output_files(row)
            if isinstance(file, dict) and file.get("library_path")]


def generation_records(db_path=None) -> Callable[[Path], dict]:
    rows = load_rows(db_path)

    def generation_of(video: Path) -> dict:
        row = _match_video_row(Path(video), rows)
        if row is None:
            return provenance.reconstructed("origenerator")
        return _generation_provenance(row)

    return generation_of


def published_actions(db_path=None) -> Callable[[lanes.AiVideo], tuple[str, ...] | None]:
    rows = load_rows(db_path)
    brought_in = {path_key(path): row for row in rows for path in _library_paths_of(row)}

    def actions_of(clip: lanes.AiVideo) -> tuple[str, ...] | None:
        row = (_match_video_row(clip.video, rows) if clip.source == lanes.ORIGENERATOR_SOURCE
               else brought_in.get(path_key(clip.upscale)))
        published = None if row is None else row.get(PUBLISHED_ACTIONS)
        return None if published is None else tuple(_decoded(published, list))

    return actions_of


def load_rows(db_path) -> list[dict]:
    return origenerator_gallery.rows(COLUMNS, optional=(OWN_PROVENANCE, PUBLISHED_ACTIONS),
                                     db_path=db_path)


def _match_video_row(video_path: Path, rows: list[dict]) -> dict | None:
    key = frame_name(strip_uniquifier(video_path.stem) + video_path.suffix)
    for row in rows:
        if key in _output_frame_names(row):
            return row
    return None


_ORIGENERATOR_IMPORTER_PLACEHOLDERS = frozenset({"unknown", "imported"})


def _generation_provenance(row: dict) -> dict:
    its_own = _decoded(row.get(OWN_PROVENANCE), dict)
    if its_own:
        return its_own
    return provenance.reconstructed(
        "origenerator",
        method=_workflow_or_none(row.get("workflow_name")),
        method_version=_workflow_or_none(row.get("workflow_version")))


def _workflow_or_none(column: str | None) -> str | None:
    return None if not column or column in _ORIGENERATOR_IMPORTER_PLACEHOLDERS else column


def _decoded(raw: str | None, kind: type[dict] | type[list]):
    if not raw:
        return kind()
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return kind()
    return value if isinstance(value, kind) else kind()


def _output_frame_names(row: dict) -> set[str]:
    return {
        frame_name(f.get("filename"))
        for f in _row_output_files(row)
        if isinstance(f, dict)
    }


def _row_output_files(row: dict) -> list:
    return _decoded(row.get("output_files"), list)
