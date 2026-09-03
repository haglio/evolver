"""Build a video's metadata sidecar from Origenerator's own gallery database.

Origenerator is a sibling video-generation app that drops its finished videos in
``0_inbox/origenerator/``. To Evolver it is a normal external content source, no
different from Provider: Evolver *pulls* what it needs and Origenerator never reaches
back. Where the Provider strategy scrapes prompts from a website, this one reads them
straight from Origenerator's ``generations`` database (read-only) — the same
authoritative record its own gallery groups by — and shapes them into the sidecar
schema the downstream browser consumes (a ``video`` block, plus a ``source_image``
block for the start frame an image-to-video clip was animated from).

The only knowledge of Origenerator's schema that lives here is the handful of
column/param names read below; keeping that knowledge on Evolver's side is the
whole point of the pull direction.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path

import config
from util.ffprobe import video_dimensions
from util.media_files import strip_uniquifier

# Columns read from Origenerator's ``generations`` table. ``params_json`` carries
# the model/LoRA/input_image a run used; the prompts and seed are first-class.
_SELECT = (
    "SELECT prompt_id, positive_prompt, negative_prompt, seed, "
    "params_json, output_files, created_at FROM generations"
)

# Param keys naming the model a run used, most-specific first — covers every
# Origenerator workflow (WAN i2v/t2i use unet_high, Flux uses unet, SDXL uses
# checkpoint). The first present wins; its filename is cleaned to a bare label.
_MODEL_KEYS = ("unet_high", "unet", "checkpoint", "unet_low")
_MODEL_EXT_RE = re.compile(r"\.(safetensors|ckpt|pt|pth|gguf|sft|bin)$", re.IGNORECASE)

# ComfyUI's LoadImage annotates a non-input source as "name [output|input|temp]".
_TYPE_ANNOTATIONS = ("[output]", "[input]", "[temp]")

# Aspect ratios a raw WxH is snapped to for display when it lands close enough.
_COMMON_RATIOS = ((16, 9), (9, 16), (1, 1), (4, 3), (3, 4), (3, 2), (2, 3),
                  (21, 9), (9, 21), (5, 4), (4, 5))


def build_metadata(video_path, db_path=None) -> dict:
    """The sidecar payload for an Origenerator video, from its generation row.

    Matches ``video_path`` to the generation that produced it (by output
    filename), builds the ``video`` block from that row, and — when the clip was
    animated from a generated start frame — resolves and adds a ``source_image``
    block from the image row that frame came from. Raises ``LookupError`` when no
    row produced this file (so the stage records a retryable failure marker),
    ``FileNotFoundError`` when the database is absent.
    """
    video_path = Path(video_path)
    db_path = Path(db_path) if db_path is not None else config.ORIGENERATOR_DB_PATH
    if not db_path.exists():
        raise FileNotFoundError(f"Origenerator database not found: {db_path}")

    rows = _load_rows(db_path)
    row = _match_video_row(video_path, rows)
    if row is None:
        raise LookupError(f"No Origenerator generation produced {video_path.name}")

    payload: dict = {"video": _video_block(row, video_path)}
    image_row = _find_source_image_row(row, rows)
    if image_row is not None:
        source_block = _source_image_block(image_row)
        if source_block:
            payload["source_image"] = source_block
    return payload


def _load_rows(db_path: Path) -> list[dict]:
    """Every generation row, read from a fresh read-only connection.

    Opened ``mode=ro`` so a running Origenerator (which owns the file) is never
    at risk of a write from here, and so a wrong path fails loudly instead of
    creating an empty database.
    """
    conn = _connect_ro(db_path)
    try:
        cursor = conn.execute(_SELECT)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        conn.close()


def _connect_ro(db_path: Path) -> sqlite3.Connection:
    """A read-only connection to Origenerator's database, opened by URI so a wrong
    path fails loudly instead of creating an empty file."""
    uri = db_path.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=5.0)


def _match_video_row(video_path: Path, rows: list[dict]) -> dict | None:
    """The row whose output files include ``video_path`` (uniquifier stripped)."""
    key = _frame_name(strip_uniquifier(video_path.stem) + video_path.suffix)
    for row in rows:
        if key in _output_frame_names(row):
            return row
    return None


def _find_source_image_row(video_row: dict, rows: list[dict]) -> dict | None:
    """The image row whose output matches ``video_row``'s ``input_image``.

    None when the row has no input image (a text-to-video clip) or the start
    frame was hand-picked/external/since-deleted rather than a generation of its
    own — the clip then simply carries no ``source_image`` block.
    """
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


def _source_image_block(row: dict) -> dict:
    block: dict = {}
    _put(block, "positive_prompt", row.get("positive_prompt"))
    _put(block, "negative_prompt", row.get("negative_prompt"))
    _put(block, "model", _model_label(_parse_params(row)))
    _put(block, "seed", _seed_str(row))
    _put(block, "created", _created_date(row))
    return block


def _put(block: dict, key: str, value) -> None:
    """Record ``key`` only when it has a non-empty value — a sparse sidecar, so a
    missing field never splits a group from an otherwise-identical one."""
    if value:
        block[key] = value


def _model_label(params: dict) -> str:
    """A bare model name from a row's params (first present of ``_MODEL_KEYS``)."""
    for key in _MODEL_KEYS:
        value = params.get(key)
        if value:
            base = str(value).replace("\\", "/").rsplit("/", 1)[-1]
            return _MODEL_EXT_RE.sub("", base)
    return ""


def _seed_str(row: dict) -> str:
    seed = row.get("seed")
    return "" if seed is None else str(seed)


def _created_date(row: dict) -> str:
    """The date part of a row's ``created_at`` timestamp ("YYYY-MM-DD ...")."""
    return (row.get("created_at") or "").split(" ")[0].split("T")[0]


def _aspect_ratio(width: int, height: int) -> str:
    """A display ratio for ``width``x``height`` — a common ratio when close, else
    the reduced fraction. Empty for a degenerate size."""
    if width <= 0 or height <= 0:
        return ""
    target = width / height
    for a, b in _COMMON_RATIOS:
        if abs(a / b - target) <= 0.05:
            return f"{a}:{b}"
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _parse_params(row: dict) -> dict:
    """Parse a row's ``params_json`` into a dict, tolerating bad data."""
    raw = row.get("params_json")
    if not raw:
        return {}
    try:
        params = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return params if isinstance(params, dict) else {}


def _output_frame_names(row: dict) -> set[str]:
    """The comparison keys for every file a row produced (see :func:`_frame_name`)."""
    return {
        _frame_name(f.get("filename"))
        for f in _row_output_files(row)
        if isinstance(f, dict)
    }


def _row_output_files(row: dict) -> list:
    """Parse a row's ``output_files`` JSON into a list, tolerating bad data."""
    raw = row.get("output_files")
    if not raw:
        return []
    try:
        files = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return files if isinstance(files, list) else []


def _frame_name(ref: str | None) -> str:
    """A filename's comparison key: basename, lowercased, any ``[output]``-style
    annotation stripped — so a LoadImage reference and a stored output filename
    match by the plain file they name (mirrors Origenerator's own matching)."""
    ref = ref or ""
    stem, _, tag = ref.rpartition(" ")
    if stem and tag in _TYPE_ANNOTATIONS:
        ref = stem
    return ref.replace("\\", "/").rsplit("/", 1)[-1].lower()
