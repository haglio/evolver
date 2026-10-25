"""Stage: sync the library's favorites into a Chrome bookmarks folder."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app_support.favorites import Favorite
from app_support.file_channel import write_whole

import config
from util import sidecar

log = logging.getLogger(__name__)

_PROFILE_INFO_KEY = "profile"
_PROFILE_CACHE_KEY = "info_cache"
_BOOKMARKS_BAR_KEY = "bookmark_bar"


@dataclass
class BookmarksSyncResult:
    synced: int = 0
    no_url: int = 0
    bad_url: int = 0
    profile_missing: bool = False
    write_error: str = ""

    @property
    def ok(self) -> bool:
        return not (self.profile_missing or self.write_error)


@dataclass(frozen=True)
class _Favorites:
    """The web addresses the favorites carry, and what reading them found."""

    urls: list[str] = field(default_factory=list)
    no_url: int = 0
    bad_url: int = 0


def run(
    *,
    chrome_user_data_dir: Path | None = None,
    chrome_profile_name: str | None = None,
    bookmarks_folder_name: str | None = None,
) -> BookmarksSyncResult:
    """Write the favorites' web URLs into one folder of a Chrome profile.

    The three things this stage reaches for in a browser profile on this
    machine are arguments rather than names to grep the body for. They are
    resolved here rather than in the signature: a default is evaluated at
    import, which would freeze the value past ``override_config``.
    """
    chrome_user_data_dir = (
        config.CHROME_USER_DATA_DIR if chrome_user_data_dir is None else chrome_user_data_dir
    )
    chrome_profile_name = (
        config.CHROME_PROFILE_NAME if chrome_profile_name is None else chrome_profile_name
    )
    bookmarks_folder_name = (
        config.CHROME_BOOKMARKS_FOLDER_NAME
        if bookmarks_folder_name is None
        else bookmarks_folder_name
    )

    result = BookmarksSyncResult()
    log.info("=== Stage: bookmarks -> Chrome profile %s ===", chrome_profile_name)
    log.info("CHROME USER DATA: %s", chrome_user_data_dir)

    if not config.METADATA_DIR.is_dir():
        log.info("The library's records cannot be reached. Skipping bookmarks sync.")
        return result
    favorites = _pages_of(sidecar.library_favorites())
    result.no_url = favorites.no_url
    result.bad_url = favorites.bad_url

    profile_dir = _find_profile_dir(chrome_user_data_dir, chrome_profile_name)
    if profile_dir is None:
        result.profile_missing = True
        log.error(
            "Chrome profile named %r was not found under %s.",
            chrome_profile_name,
            chrome_user_data_dir,
        )
        return result

    bookmarks_path = profile_dir / "Bookmarks"
    try:
        data = _load_bookmarks(bookmarks_path)
        added = _upsert_folder(data, favorites.urls, bookmarks_folder_name)
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
        "Bookmarks sync done. Synced: %d, No URL: %d, Bad URL: %d, Target: %s",
        result.synced,
        result.no_url,
        result.bad_url,
        bookmarks_path,
    )
    return result


def _pages_of(favorites: Iterable[Favorite]) -> _Favorites:
    urls: list[str] = []
    no_url = bad_url = 0
    for favorite in favorites:
        if not favorite.page:
            no_url += 1
            continue
        parsed = urlparse(favorite.page)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            bad_url += 1
            log.warning("Skipping a favorite whose page is no web address: %s", favorite.video)
            continue
        urls.append(favorite.page)
    return _Favorites(urls=list(dict.fromkeys(urls)), no_url=no_url, bad_url=bad_url)


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

    wanted = set(urls)
    kept = [child.get("url") for child in folder.get("children", []) if child.get("url") in wanted]
    folder["children"] = []
    for url in dict.fromkeys([*kept, *urls]):
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
    # indent=3 and newline="\n" because that is how Chrome writes this file,
    # and it is Chrome's to read back.
    write_whole(path, json.dumps(data, indent=3) + "\n", newline="\n")
