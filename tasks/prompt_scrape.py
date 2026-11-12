from __future__ import annotations

import datetime
import json
import logging
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import parsedate
from pathlib import Path
from urllib.parse import urlparse

from app_support.gallery_rows import VideoRows

import config
from tasks.origenerator_commands import GalleryRecords, write_gallery_entries
from util import lanes, orientation, origenerator_gallery, relative_dates
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
from util.origenerator_gallery import EVOLVER_UPSCALE
from util.scraped_records import ScrapedRecords
from util.stage_result import StageResult
from util.versions import source_stem

log = logging.getLogger(__name__)

_CONTENT_PANEL_SELECTOR = r"main > div > div > div.flex-1.overflow-hidden > div.font-regular"

SOURCE_IMAGE_BLOCK = "source_image"


@dataclass
class PromptScrapeResult(StageResult):
    newly_scraped: int = 0
    already_scraped: int = 0
    skipped_failed: int = 0
    no_scrape_strat: int = 0
    errors: int = 0
    handed_over: int = 0

    @property
    def ok(self) -> bool:
        return self.errors == 0


def run(*, sorted_dir: Path | None = None,
        browser_profile_dir: Path | None = None,
        scraped: ScrapedRecords | None = None,
        gallery: GalleryRecords | None = None) -> PromptScrapeResult:
    sorted_dir = config.SORTED_DIR if sorted_dir is None else sorted_dir
    browser_profile_dir = (
        config.PROMPT_BROWSER_PROFILE_DIR if browser_profile_dir is None
        else browser_profile_dir
    )
    scraped = kept_for_the_gallery() if scraped is None else scraped
    gallery = GalleryRecords() if gallery is None else gallery
    result = PromptScrapeResult()
    log.info("=== Stage: scrape AI metadata ===")
    log.info("SORTED DIR: %s", sorted_dir)

    in_the_gallery = _recorded_in_the_gallery()
    if in_the_gallery is None:
        return result
    browser = find_browser_executable()
    if browser is None:
        log.warning("No supported browser found; Provider scraping is unavailable this run.")
    strategies = _build_strategies(browser, browser_profile_dir)

    for source_dir in child_dirs(sorted_dir):
        source = source_dir.name
        if lanes.sent_by_origenerator(source):
            continue
        strategy = strategies.get(source)

        for video in sorted(library_videos(source_dir)):
            if strategy is None:
                result.no_scrape_strat += 1
                continue

            orient = video.relative_to(source_dir).parts[0]
            if orient not in orientation.SORTED:
                continue

            upscale = lanes.upscale_of(source, orient, video.stem)
            if upscale is None:
                continue
            if scraped.staged(upscale) is not None or in_the_gallery(upscale):
                result.already_scraped += 1
                continue
            if scraped.failed(upscale):
                result.skipped_failed += 1
                continue

            try:
                payload = strategy(video)
            except Exception as exc:
                result.errors += 1
                scraped.mark_failed(upscale, video, exc)
                log.exception("Metadata build failed for: %s", video)
                continue

            scraped.stage(upscale, payload)
            result.newly_scraped += 1
            log.info("Scraped the record of %s", video)

    result.handed_over = sum(hand_over_the_record_of(upscale, scraped=scraped, gallery=gallery)
                             for upscale, _record in scraped.waiting() if upscale.is_file())
    log.info(
        "Metadata scrape done. Scraped: %d, Already: %d, Skipped failed: %d, No strategy: %d, "
        "Errors: %d, Handed to Origenerator's gallery: %d",
        result.newly_scraped,
        result.already_scraped,
        result.skipped_failed,
        result.no_scrape_strat,
        result.errors,
        result.handed_over,
    )
    return result


def hand_over_the_record_of(upscale: Path, *, scraped: ScrapedRecords,
                            gallery: GalleryRecords) -> bool:
    record = scraped.staged(upscale)
    if record is None:
        return False
    answer = gallery.record(upscale, record)
    if answer is None or not answer.done:
        log.info("Origenerator's gallery did not take the record of %s; it waits for the next run",
                 upscale)
        return False
    scraped.drop(upscale)
    return True


def tell_the_gallery_of_the_filed(
        _source: str, upscale: Path, *, scraped: ScrapedRecords | None = None,
        gallery: GalleryRecords | None = None,
        write_entries: Callable[[], object] = write_gallery_entries) -> None:
    hand_over_the_record_of(
        upscale, scraped=kept_for_the_gallery() if scraped is None else scraped,
        gallery=GalleryRecords() if gallery is None else gallery)
    write_entries()


def kept_for_the_gallery() -> ScrapedRecords:
    return ScrapedRecords(config.SCRAPED_RECORDS_FILE)


def made_from_words_alone(upscale: Path) -> bool | None:
    scraped = kept_for_the_gallery().staged(upscale)
    return None if not scraped else SOURCE_IMAGE_BLOCK not in scraped


GALLERY_COLUMNS = ("prompt_id", "output_files", "positive_prompt")


def _recorded_in_the_gallery() -> Callable[[Path], bool] | None:
    try:
        prompted = [row for row in origenerator_gallery.rows(
            GALLERY_COLUMNS, optional=(EVOLVER_UPSCALE,))
            if row.get("positive_prompt")]
    except FileNotFoundError:
        prompted = []
    except sqlite3.Error:
        log.warning("Could not read Origenerator's gallery; the scrape waits for a run that can.",
                    exc_info=True)
        return None
    found = VideoRows(prompted)
    return lambda upscale: found(upscale) is not None


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
            payload[SOURCE_IMAGE_BLOCK] = image_data
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
    strategies = {}
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
