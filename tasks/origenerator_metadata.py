from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from pathlib import Path

from util import origenerator_gallery, provenance, sidecar
from util.ffprobe import video_dimensions
from util.library_records import FRAME_OF_VIDEO_BLOCK, SOURCE_IMAGE_BLOCK
from util.media_files import strip_uniquifier

COLUMNS = ("prompt_id", "workflow_name", "workflow_version", "positive_prompt",
            "negative_prompt", "seed", "params_json", "output_files", "created_at")

OWN_PROVENANCE = "provenance"

MODEL_KEYS = ("unet_high", "unet", "checkpoint", "unet_low")
_MODEL_EXT_RE = re.compile(r"\.(safetensors|ckpt|pt|pth|gguf|sft|bin)$", re.IGNORECASE)

# ComfyUI's LoadImage annotation.
_TYPE_ANNOTATIONS = ("[output]", "[input]", "[temp]")

_COMMON_RATIOS = ((16, 9), (9, 16), (1, 1), (4, 3), (3, 4), (3, 2), (2, 3),
                  (21, 9), (9, 21), (5, 4), (4, 5))
_RATIO_TOLERANCE = 0.05


def build_metadata(video_path, db_path=None) -> dict:
    video_path = Path(video_path)
    rows = load_rows(db_path)
    row = _match_video_row(video_path, rows)
    if row is None:
        raise LookupError(f"No Origenerator generation produced {video_path.name}")

    payload: dict = {
        "video": _video_block(row, video_path),
        provenance.BLOCK: {provenance.GENERATION: _generation_provenance(row)},
    }
    source_block = source_image_block_of(row, rows)
    if source_block:
        payload[SOURCE_IMAGE_BLOCK] = source_block
    return payload


def source_image_block_of(row: dict, rows: list[dict]) -> dict:
    image_row = _find_source_image_row(row, rows)
    if image_row is None:
        return {}
    block = _source_image_block(image_row)
    video = _t2v_video_with_the_start_frame_in(image_row, row, rows)
    return {**block, FRAME_OF_VIDEO_BLOCK: video} if video and block else block


def _t2v_video_with_the_start_frame_in(image_row: dict, video_row: dict,
                                       rows: list[dict]) -> dict | None:
    frames = _output_frame_names(image_row)
    for row in rows:
        if row is video_row or _frame_name(_parse_params(row).get("input_image")) not in frames:
            continue
        for path in _library_paths_of(row):
            record = _record_of(path)
            video = record.get("video")
            if not record.get(SOURCE_IMAGE_BLOCK) and isinstance(video, dict) and video.get("prompt"):
                return video
    return None


def _library_paths_of(row: dict) -> list[Path]:
    return [Path(file["library_path"]) for file in _row_output_files(row)
            if isinstance(file, dict) and file.get("library_path")]


def _record_of(video: Path) -> dict:
    try:
        return sidecar.read(sidecar.sidecar_path(video))
    except ValueError:
        return {}


def generation_records(db_path=None) -> Callable[[Path], dict]:
    rows = load_rows(db_path)

    def generation_of(video: Path) -> dict:
        row = _match_video_row(Path(video), rows)
        if row is None:
            return provenance.reconstructed("origenerator")
        return _generation_provenance(row)

    return generation_of


def load_rows(db_path) -> list[dict]:
    return origenerator_gallery.rows(COLUMNS, optional=(OWN_PROVENANCE,),
                                     db_path=db_path)


def video_row_named(name: str, rows: list[dict]) -> dict | None:
    return _match_video_row(Path(name), rows)


def _match_video_row(video_path: Path, rows: list[dict]) -> dict | None:
    key = _frame_name(strip_uniquifier(video_path.stem) + video_path.suffix)
    for row in rows:
        if key in _output_frame_names(row):
            return row
    return None


def _find_source_image_row(video_row: dict, rows: list[dict]) -> dict | None:
    target = _frame_name(_parse_params(video_row).get("input_image"))
    if not target:
        return None
    for row in rows:
        if row.get("prompt_id") == video_row.get("prompt_id"):
            continue
        if target in _output_frame_names(row):
            return row
    return None


def _video_block(row: dict, video_path: Path) -> dict:
    block: dict = {}
    _put(block, "prompt", row.get("positive_prompt"))
    _put(block, "model", _model_label(_parse_params(row)))
    dims = video_dimensions(video_path)
    if dims is not None:
        width, height = dims
        _put(block, "resolution", f"{width}x{height}")
        _put(block, "aspect_ratio", _aspect_ratio(width, height))
    _put(block, "seed", _seed_str(row))
    _put(block, "created", _created_date(row))
    return block


_IMPORT_PLACEHOLDERS = frozenset({"unknown", "imported"})


def _generation_provenance(row: dict) -> dict:
    its_own = _decoded(row.get(OWN_PROVENANCE), dict)
    if its_own:
        return its_own
    return provenance.reconstructed(
        "origenerator",
        method=_named(row.get("workflow_name")),
        method_version=_named(row.get("workflow_version")))


def _named(column: str | None) -> str | None:
    return None if not column or column in _IMPORT_PLACEHOLDERS else column


def _source_image_block(row: dict) -> dict:
    block: dict = {}
    _put(block, "positive_prompt", row.get("positive_prompt"))
    _put(block, "negative_prompt", row.get("negative_prompt"))
    _put(block, "model", _model_label(_parse_params(row)))
    _put(block, "seed", _seed_str(row))
    _put(block, "created", _created_date(row))
    return block


def _put(block: dict, key: str, value) -> None:
    if value:
        block[key] = value


def _model_label(params: dict) -> str:
    for key in MODEL_KEYS:
        value = params.get(key)
        if value:
            base = str(value).replace("\\", "/").rsplit("/", 1)[-1]
            return _MODEL_EXT_RE.sub("", base)
    return ""


def _seed_str(row: dict) -> str:
    seed = row.get("seed")
    return "" if seed is None else str(seed)


def _created_date(row: dict) -> str:
    return (row.get("created_at") or "").split(" ")[0].split("T")[0]


def _aspect_ratio(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return ""
    target = width / height
    for a, b in _COMMON_RATIOS:
        if abs(a / b - target) <= _RATIO_TOLERANCE:
            return f"{a}:{b}"
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _parse_params(row: dict) -> dict:
    return _decoded(row.get("params_json"), dict)


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
        _frame_name(f.get("filename"))
        for f in _row_output_files(row)
        if isinstance(f, dict)
    }


def _row_output_files(row: dict) -> list:
    return _decoded(row.get("output_files"), list)


def _frame_name(ref: str | None) -> str:
    ref = ref or ""
    stem, _, tag = ref.rpartition(" ")
    if stem and tag in _TYPE_ANNOTATIONS:
        ref = stem
    return ref.replace("\\", "/").rsplit("/", 1)[-1].lower()
