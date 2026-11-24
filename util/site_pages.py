from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from util.versions import source_stem


def page_at(base_url: str, video: Path) -> str:
    return f"{base_url}/image/{source_stem(video.stem)}"


def page_of(video: Path, site_page_bases: Mapping[str, str]) -> str | None:
    base_url = site_page_bases.get(video.parent.name)
    return None if base_url is None else page_at(base_url, video)
