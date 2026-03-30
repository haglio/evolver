"""Stage: sync Fun Time favorites into a Chrome bookmarks folder."""

from __future__ import annotations

import csv
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import config

log = logging.getLogger(__name__)

_HYPERLINK_URL_RE = re.compile(r'^=HYPERLINK\("([^"]+)"[;,]', re.IGNORECASE)
_PROFILE_INFO_KEY = "profile"
_PROFILE_CACHE_KEY = "info_cache"
_BOOKMARKS_BAR_KEY = "bookmark_bar"


@dataclass
class BookmarksSyncResult:
    synced: int = 0
    pruned: int = 0
    no_url: int = 0
    bad_url: int = 0
    source_missing: bool = False
    profile_missing: bool = False
    write_error: str = ""

    @property
    def ok(self) -> bool:
        return not (self.profile_missing or self.write_error)


def run() -> BookmarksSyncResult:
    result = BookmarksSyncResult()
    log.info("=== Stage 4: bookmarks -> Chrome profile %s ===", config.CHROME_PROFILE_NAME)
    log.info("SOURCE CSV: %s", config.FUN_TIME_FAVS_FILE)
    log.info("CHROME USER DATA: %s", config.CHROME_USER_DATA_DIR)

    urls = _read_urls(result)
    if result.source_missing:
        log.info("Favorites CSV not found. Skipping bookmarks sync.")
        return result

    profile_dir = _find_profile_dir(config.CHROME_USER_DATA_DIR, config.CHROME_PROFILE_NAME)
    if profile_dir is None:
        result.profile_missing = True
        log.error(
            "Chrome profile named %r was not found under %s.",
            config.CHROME_PROFILE_NAME,
            config.CHROME_USER_DATA_DIR,
        )
        return result

    bookmarks_path = profile_dir / "Bookmarks"
    try:
        data = _load_bookmarks(bookmarks_path)
        added = _upsert_folder(data, urls, config.CHROME_BOOKMARKS_FOLDER_NAME)
        _atomic_write_json(bookmarks_path, data)
    except OSError as exc:
        result.write_error = str(exc)
        log.exception("Failed to write Chrome bookmarks file: %s", bookmarks_path)
        return result
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        result.write_error = str(exc)
        log.exception("Chrome bookmarks file is invalid: %s", bookmarks_path)
        return result

    result.synced = added
    log.info(
        "Stage 4 done. Synced: %d, No URL: %d, Bad URL: %d, Target: %s",
        result.synced,
        result.no_url,
        result.bad_url,
        bookmarks_path,
    )
    return result


def _read_urls(result: BookmarksSyncResult) -> list[str]:
    path = config.FUN_TIME_FAVS_FILE
    if not path.is_file():
        result.source_missing = True
        return []

    fieldnames, rows = _load_and_prune_rows(path, result)

    urls: list[str] = []
    seen: set[str] = set()
    for row in rows:
        raw_value = (row.get("web_url") or "").strip()
        if not raw_value:
            result.no_url += 1
            continue

        url = _extract_url(raw_value)
        if url is None:
            result.bad_url += 1
            log.warning("Skipping invalid web_url cell: %s", raw_value)
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)

    if result.pruned:
        _write_rows(path, fieldnames, rows)
        log.info("Removed %d stale favorite row(s) whose source file is gone.", result.pruned)
    return urls


def _load_and_prune_rows(path: Path, result: BookmarksSyncResult) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        file_column = _file_column_name(fieldnames)
        kept_rows: list[dict[str, str]] = []
        for row in reader:
            if file_column and _prune_or_rewire_row(row, file_column, path.parent, result):
                result.pruned += 1
                continue
            kept_rows.append(row)
    return fieldnames, kept_rows


def _file_column_name(fieldnames: list[str]) -> str | None:
    normalized = {name.lstrip("\ufeff"): name for name in fieldnames}
    for candidate in ("file", "local_file"):
        match = normalized.get(candidate)
        if match is not None:
            return match
    return None


def _prune_or_rewire_row(
    row: dict[str, str],
    file_column: str,
    base_dir: Path,
    result: BookmarksSyncResult,
) -> bool:
    raw_value = (row.get(file_column) or "").strip()
    if not raw_value:
        return False
    normalized_column = file_column.lstrip("\ufeff")
    if normalized_column == "local_file" and not _looks_like_filesystem_reference(raw_value):
        return False

    candidate = _extract_local_path(raw_value, base_dir)
    return not candidate.exists()


def _extract_local_path(value: str, base_dir: Path) -> Path:
    match = _HYPERLINK_URL_RE.match(value)
    candidate = match.group(1) if match else value
    parsed = urlparse(candidate)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path.lstrip("/")))

    path = Path(candidate)
    if not path.is_absolute():
        path = base_dir / path
    return path


def _looks_like_filesystem_reference(value: str) -> bool:
    match = _HYPERLINK_URL_RE.match(value)
    candidate = match.group(1) if match else value
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        return False
    if parsed.scheme == "file":
        return True
    if re.match(r"^[A-Za-z]:[\\/]", candidate):
        return True
    if candidate.startswith(("\\\\", "/", "./", "../")):
        return True
    return "\\" in candidate or "/" in candidate




def _write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temp_path.replace(path)


def _extract_url(value: str) -> str | None:
    match = _HYPERLINK_URL_RE.match(value)
    candidate = match.group(1) if match else value
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _find_profile_dir(user_data_dir: Path, profile_name: str) -> Path | None:
    local_state_path = user_data_dir / "Local State"
    if not local_state_path.is_file():
        return None

    with local_state_path.open("r", encoding="utf-8") as fh:
        local_state = json.load(fh)

    info_cache = (
        local_state.get(_PROFILE_INFO_KEY, {})
        .get(_PROFILE_CACHE_KEY, {})
    )
    if not isinstance(info_cache, dict):
        return None

    for directory_name, entry in info_cache.items():
        if isinstance(entry, dict) and entry.get("name") == profile_name:
            return user_data_dir / directory_name
    return None


def _load_bookmarks(bookmarks_path: Path) -> dict:
    if not bookmarks_path.is_file():
        return {
            "checksum": "",
            "roots": {
                _BOOKMARKS_BAR_KEY: _new_root_folder("1", "Bookmarks bar"),
                "other": _new_root_folder("2", "Other bookmarks"),
                "synced": _new_root_folder("3", "Mobile bookmarks"),
            },
            "version": 1,
        }

    with bookmarks_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _new_root_folder(folder_id: str, name: str) -> dict:
    now = _chrome_timestamp()
    return {
        "children": [],
        "date_added": now,
        "date_last_used": "0",
        "date_modified": now,
        "guid": str(uuid.uuid4()),
        "id": folder_id,
        "name": name,
        "type": "folder",
    }


def _upsert_folder(data: dict, urls: list[str], folder_name: str) -> int:
    roots = data["roots"]
    bookmark_bar = roots[_BOOKMARKS_BAR_KEY]
    children = bookmark_bar.setdefault("children", [])

    matching = [child for child in children if child.get("type") == "folder" and child.get("name") == folder_name]
    folder = matching[0] if matching else None
    for extra in matching[1:]:
        children.remove(extra)

    next_id = _next_bookmark_id(data)
    now = _chrome_timestamp()
    if folder is None:
        folder = {
            "children": [],
            "date_added": now,
            "date_last_used": "0",
            "date_modified": now,
            "guid": str(uuid.uuid4()),
            "id": str(next_id),
            "name": folder_name,
            "type": "folder",
        }
        children.append(folder)
        next_id += 1
    else:
        folder["date_modified"] = now

    folder["children"] = []
    for url in urls:
        folder["children"].append(
            {
                "date_added": now,
                "date_last_used": "0",
                "guid": str(uuid.uuid4()),
                "id": str(next_id),
                "name": _bookmark_name(url),
                "type": "url",
                "url": url,
            }
        )
        next_id += 1

    bookmark_bar["date_modified"] = now
    return len(urls)


def _next_bookmark_id(data: dict) -> int:
    highest = 0

    def visit(node: object) -> None:
        nonlocal highest
        if isinstance(node, dict):
            raw_id = node.get("id")
            if isinstance(raw_id, str) and raw_id.isdigit():
                highest = max(highest, int(raw_id))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(data)
    return highest + 1


def _bookmark_name(url: str) -> str:
    parsed = urlparse(url)
    tail = parsed.path.rstrip("/").split("/")[-1]
    if tail:
        return f"{parsed.netloc} - {tail}"
    return url


def _chrome_timestamp() -> str:
    epoch = datetime(1601, 1, 1, tzinfo=UTC)
    now = datetime.now(tz=UTC)
    return str(int((now - epoch).total_seconds() * 1_000_000))


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.name + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=3)
        fh.write("\n")
    temp_path.replace(path)
