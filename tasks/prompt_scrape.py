from __future__ import annotations

import datetime
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import parsedate
from pathlib import Path
from urllib.parse import urlparse

import config
from tasks import origenerator_metadata
from util import lanes, orientation, provenance, relative_dates, sidecar, video_kind
from util.headless_browser import fetch_dom, find_browser_executable
from util.html_query import (
    Node,
    extract_label_values,
    find_all_by_tag,
    parse_document,
    query_selector,
    text_content,
)
from util.media_files import child_dirs, library_videos
from util.sidecar import sidecar_path, upscaled_video_path
from util.stage_result import StageResult
from util.versions import source_stem

log = logging.getLogger(__name__)

_CONTENT_PANEL_SELECTOR = r"main > div > div > div.flex-1.overflow-hidden > div.font-regular"


@dataclass
class PromptScrapeResult(StageResult):
    newly_scraped: int = 0
    already_scraped: int = 0
    skipped_failed: int = 0
    no_scrape_strat: int = 0
    errors: int = 0

    @property
    def ok(self) -> bool:
        return self.errors == 0


def run(*, sorted_dir: Path | None = None,
        browser_profile_dir: Path | None = None) -> PromptScrapeResult:
    sorted_dir = config.SORTED_DIR if sorted_dir is None else sorted_dir
    browser_profile_dir = (
        config.PROMPT_BROWSER_PROFILE_DIR if browser_profile_dir is None
        else browser_profile_dir
    )
    result = PromptScrapeResult()
    log.info("=== Stage: scrape AI metadata ===")
    log.info("SORTED DIR: %s", sorted_dir)
    log.info("METADATA DIR: %s", config.METADATA_DIR)

    browser = find_browser_executable()
    if browser is None:
        log.warning("No supported browser found; Provider scraping is unavailable this run.")
    strategies = _build_strategies(browser, browser_profile_dir)

    for source_dir in child_dirs(sorted_dir):
        source = source_dir.name
        strategy = strategies.get(source)

        for video in sorted(library_videos(source_dir)):
            if strategy is None:
                result.no_scrape_strat += 1
                continue

            orient = video.relative_to(source_dir).parts[0]
            if orient not in orientation.SORTED:
                continue

            output_path = sidecar_path(upscaled_video_path(source, orient, video.stem))
            if _already_scraped(output_path):
                result.already_scraped += 1
                continue
            if _failure_marker_path(output_path).exists():
                result.skipped_failed += 1
                continue

            try:
                payload = strategy(video)
            except Exception as exc:
                result.errors += 1
                _write_failure_marker(output_path, video, exc)
                log.exception("Metadata build failed for: %s", video)
                continue

            def keep_what_landed_first(current: dict, payload=payload) -> dict:
                recorded = video_kind.kind_of(current)
                kept = video_kind.stamped(payload, recorded) if recorded else payload
                return provenance.carried_forward(current, kept)

            sidecar.update(output_path, keep_what_landed_first)
            result.newly_scraped += 1
            log.info("Wrote metadata: %s", output_path)

    log.info(
        "Metadata scrape done. Scraped: %d, Already: %d, Skipped failed: %d, No strategy: %d, Errors: %d",
        result.newly_scraped,
        result.already_scraped,
        result.skipped_failed,
        result.no_scrape_strat,
        result.errors,
    )
    return result


def _already_scraped(output_path: Path) -> bool:
    return output_path.exists() and not video_kind.only_the_video_itself(
        sidecar.read(output_path))


def _failure_marker_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".failed")


def _write_failure_marker(output_path: Path, video: Path, error: BaseException) -> None:
    marker = _failure_marker_path(output_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{video.name}\n{error}\n", encoding="utf-8")


def _provider_image_url(video: Path, base_url: str) -> str:
    return f"{base_url}/image/{source_stem(video.stem)}"


@dataclass(frozen=True)
class _VideoFields:
    prompt: str = ""
    source_image_url: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


def _scrape_provider_video(
    video_path: Path, image_url: str, browser: Path, base_url: str, profile_dir: Path,
) -> dict[str, object]:
    image_id = image_url.rstrip("/").split("/")[-1]
    found = _VideoFields()
    for candidate in _candidate_urls(image_url, image_id, base_url):
        html = fetch_dom(candidate, browser, profile_dir=profile_dir)
        found = _folded_in(found, html, image_id, base_url)
        if found.prompt:
            break
    if not found.prompt:
        raise RuntimeError(f"Could not extract Provider video prompt for {video_path.name}")

    payload: dict[str, object] = {"video": {"prompt": found.prompt, **found.metadata}}
    if found.source_image_url:
        image_data = _scrape_source_image(
            found.source_image_url, browser, profile_dir=profile_dir)
        if image_data:
            payload["source_image"] = image_data
    return payload


_VIDEO_PATHS_BY_HOW_IT_WAS_MADE = ("video", "text-to-video", "image-to-video")


def _candidate_urls(page_its_name_maps_to: str, image_id: str, base_url: str) -> list[str]:
    return [
        page_its_name_maps_to,
        *(f"{base_url}/{path}/{image_id}" for path in _VIDEO_PATHS_BY_HOW_IT_WAS_MADE),
    ]


def _folded_in(found: _VideoFields, html: str, image_id: str,
               base_url: str) -> _VideoFields:
    document = parse_document(html)
    panel = query_selector(document, _CONTENT_PANEL_SELECTOR)
    if panel is not None:
        found = _VideoFields(
            prompt=_extract_prompt_text(panel),
            source_image_url=_extract_source_image_url(panel, base_url),
            metadata=_extract_metadata_fields(document),
        )
    if found.prompt:
        return found
    embedded = _extract_provider_embedded_metadata(html, image_id)
    if not embedded.prompt:
        return found
    parent_url = (f"{base_url}/image/{embedded.parent_image_id}"
                  if embedded.parent_image_id else "")
    return _VideoFields(
        prompt=embedded.prompt,
        source_image_url=found.source_image_url or parent_url,
        metadata=found.metadata or _embedded_to_video_metadata(embedded),
    )


def _scrape_source_image(url: str, browser: Path, *, profile_dir: Path) -> dict[str, str]:
    html = fetch_dom(url, browser, profile_dir=profile_dir)
    document = parse_document(html)
    panel = query_selector(document, _CONTENT_PANEL_SELECTOR)
    if panel is not None:
        fields = {
            "positive_prompt": _extract_prompt_text(panel),
            "negative_prompt": _extract_negative_prompt_text(panel),
        }
        return {key: value for key, value in fields.items() if value} | \
            _extract_metadata_fields(document)
    embedded = _extract_provider_embedded_metadata(html, url.rstrip("/").split("/")[-1])
    fields = {
        "positive_prompt": embedded.prompt,
        "negative_prompt": embedded.negative_prompt,
    }
    return {key: value for key, value in fields.items() if value} | \
        _embedded_to_image_metadata(embedded)


def _build_strategies(browser, profile_dir):
    provider_source = config.PROVIDER_SOURCE
    base_url = config.PROVIDER_BASE_URL
    strategies = {lanes.ORIGENERATOR_SOURCE: origenerator_metadata.build_metadata}
    if browser is not None:
        strategies[provider_source] = lambda video: _scrape_provider_video(
            video, _provider_image_url(video, base_url), browser, base_url, profile_dir
        )
    return strategies


def _extract_prompt_text(panel: Node) -> str:
    for child in panel.children:
        if child.tag != "div":
            continue
        inner_divs = [c for c in child.children if c.tag == "div"]
        if len(inner_divs) == 1:
            text = text_content(inner_divs[0]).strip()
            has_h2 = any(True for _ in find_all_by_tag(inner_divs[0], "h2"))
            if text and not has_h2:
                return text
    return ""


def _extract_negative_prompt_text(panel: Node) -> str:
    found_label = False
    for child in panel.children:
        if not found_label:
            text = text_content(child).strip().lower()
            if "negative prompt" in text and "max-h-80" not in child.attrs.get("class", ""):
                found_label = True
                continue
        if found_label and "max-h-80" in child.attrs.get("class", ""):
            return text_content(child).strip()
    return ""


def _extract_source_image_url(panel: Node, base_url: str) -> str:
    for img in find_all_by_tag(panel, "img"):
        src = img.attrs.get("src", "")
        if src:
            return _image_page_url_from_src(src, base_url)
    return ""


def _image_page_url_from_src(src: str, base_url: str) -> str:
    parsed = urlparse(src)
    image_id = parsed.path.strip("/").split("/")[-1]
    if not image_id:
        return ""
    return f"{base_url}/image/{image_id}"


@dataclass
class _ProviderEmbeddedMetadata:
    prompt: str = ""
    negative_prompt: str = ""
    parent_image_id: str = ""
    model: str = ""
    version: str = ""
    seed: str = ""
    aspect_ratio: str = ""
    resolution: str = ""
    quality: str = ""
    created: str = ""
    action: str = ""
    style: str = ""
    creativity: str = ""


_RECORD_REACH_CHARS = 5000


def _extract_provider_embedded_metadata(html: str, page_id: str) -> _ProviderEmbeddedMetadata:
    found: dict[str, str] = {}
    for index in _all_indices(html, page_id):
        window = html[max(0, index - _RECORD_REACH_CHARS): index + _RECORD_REACH_CHARS]
        for candidate in _as_json_and_as_a_json_string(window):
            for attribute, extract in _EMBEDDED_FIELDS:
                if not found.get(attribute):
                    found[attribute] = extract(candidate)
        if found.get("prompt"):
            break
    return _ProviderEmbeddedMetadata(**found)


def _as_json_and_as_a_json_string(window: str) -> tuple[str, str]:
    return window, window.replace('\\"', '"')


def _int_field_as_text(blob: str, field_name: str) -> str:
    value = _extract_json_int_field(blob, field_name)
    return "" if value is None else str(value)


def _resolution_field(blob: str) -> str:
    width = _extract_json_int_field(blob, "width")
    height = _extract_json_int_field(blob, "height")
    if width is None or height is None:
        return ""
    return f"{width}x{height}"


def _created_field(blob: str) -> str:
    created_at = _extract_json_string_field(blob, "createdAt")
    return _parse_provider_created_at(created_at) if created_at else ""


def _action_field(blob: str) -> str:
    raw_action = _extract_json_first_array_string(blob, "action")
    return _titlecase_action(raw_action) if raw_action else ""


_EMBEDDED_FIELDS: tuple[tuple[str, Callable[[str], str]], ...] = (
    ("prompt", lambda blob: _extract_json_string_field(blob, "prompt")),
    ("negative_prompt",
     lambda blob: _extract_nullable_json_string_field(blob, "negative_prompt")),
    ("parent_image_id",
     lambda blob: _extract_nullable_json_string_field(blob, "parent_image_id")),
    ("model", lambda blob: _extract_json_string_field(blob, "model")),
    ("version", lambda blob: _extract_json_string_field(blob, "version")),
    ("seed", lambda blob: _int_field_as_text(blob, "seed")),
    ("aspect_ratio", lambda blob: _extract_json_string_field(blob, "aspectRatio")),
    ("resolution", _resolution_field),
    ("quality", lambda blob: _extract_json_string_field(blob, "quality")),
    ("created", _created_field),
    ("action", _action_field),
    ("style", lambda blob: _extract_nullable_json_string_field(blob, "styleValue")),
    ("creativity", lambda blob: _int_field_as_text(blob, "creativity")),
)


def _extract_json_string_field(blob: str, field_name: str) -> str:
    match = re.search(rf'"{re.escape(field_name)}":"((?:\\.|[^"\\])*)"', blob)
    if not match:
        return ""
    return json.loads(f'"{match.group(1)}"')


def _extract_nullable_json_string_field(blob: str, field_name: str) -> str:
    match = re.search(rf'"{re.escape(field_name)}":(null|"((?:\\.|[^"\\])*)")', blob)
    if not match or match.group(1) == "null":
        return ""
    return json.loads(f'"{match.group(2)}"')


def _extract_json_int_field(blob: str, field_name: str) -> int | None:
    match = re.search(rf'"{re.escape(field_name)}":(\d+)', blob)
    if not match:
        return None
    return int(match.group(1))


def _extract_json_first_array_string(blob: str, field_name: str) -> str:
    match = re.search(rf'"{re.escape(field_name)}":\["([^"]+)"', blob)
    if not match:
        return ""
    return match.group(1)


def _titlecase_action(raw_action: str) -> str:
    as_written = {prefix.lower(): prefix for prefix in config.CAMERA_PREFIXES}
    words = raw_action.replace("_", " ").split()
    return " ".join(as_written.get(word.lower(), word.title()) for word in words)


def _parse_provider_created_at(value: str) -> str:
    try:
        t = parsedate(value)
        if t is not None:
            return datetime.date(t[0], t[1], t[2]).isoformat()
    except ValueError:
        log.debug("Not a usable date: %r", value, exc_info=True)
    return value


def _embedded_to_video_metadata(embedded: _ProviderEmbeddedMetadata) -> dict[str, str]:
    fields: dict[str, str] = {}
    if embedded.version:
        fields["model"] = f"Video {embedded.version}"
    elif embedded.model:
        fields["model"] = embedded.model
    fields.update({key: value for key, value in (
        ("action", embedded.action),
        ("resolution", embedded.resolution),
        ("aspect_ratio", embedded.aspect_ratio),
        ("quality", embedded.quality),
        ("seed", embedded.seed),
        ("created", embedded.created),
        ("style", embedded.style),
    ) if value})
    return fields


def _embedded_to_image_metadata(embedded: _ProviderEmbeddedMetadata) -> dict[str, str]:
    fields: dict[str, str] = {}
    if embedded.model:
        fields["model"] = embedded.model
    fields.update({key: value for key, value in (
        ("action", embedded.action),
        ("resolution", embedded.resolution),
        ("aspect_ratio", embedded.aspect_ratio),
        ("quality", embedded.quality),
        ("seed", embedded.seed),
        ("created", embedded.created),
        ("style", embedded.style),
        ("creativity", embedded.creativity),
    ) if value})
    return fields


_METADATA_LABELS = {
    "model", "action", "resolution", "aspect ratio", "quality",
    "seed", "created", "style", "creativity",
}


def _extract_metadata_fields(root: Node) -> dict[str, str]:
    fields: dict[str, str] = {}
    for label, value in extract_label_values(root, _METADATA_LABELS).items():
        key = label.replace(" ", "_")
        fields[key] = relative_dates.as_iso_date(value) if key == "created" else value
    return fields


def _all_indices(haystack: str, needle: str) -> list[int]:
    indices: list[int] = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index == -1:
            return indices
        indices.append(index)
        start = index + len(needle)
