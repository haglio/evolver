"""Stage: scrape AI prompt metadata into mirrored JSON files."""

from __future__ import annotations

import datetime
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import parsedate
from pathlib import Path

from util.html_query import (
    Node,
    extract_label_values,
    find_all_by_tag,
    parse_document,
    query_selector,
    text_content,
)
from urllib.parse import urlparse

import config
from tasks import origenerator_metadata
from tasks.purge_weird import source_stem
from util import relative_dates
from util.headless_browser import fetch_dom, find_browser_executable
from util.media_files import iter_finalized_videos
from util.sidecar import sidecar_path, upscaled_video_path, write

log = logging.getLogger(__name__)

_CONTENT_PANEL_SELECTOR = r"main > div > div > div.flex-1.overflow-hidden > div.font-regular"

# The headless browser's scratch profile, under the checkout by default because
# that is where it has always been; a caller passing its own keeps a running
# app's scratch state out of a git working tree entirely.
_BROWSER_PROFILE_DIR_NAME = ".tmp-prompt-browser-profile"


@dataclass
class PromptScrapeResult:
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
    """Scrape each newly sorted video's provenance into its mirrored sidecar.

    *sorted_dir* is the tree walked; *browser_profile_dir* is the scratch
    profile the headless browser is given. Both are sentinels rather than
    signature defaults: a default is evaluated at import, which would freeze
    whatever ``config`` held then and put the value out of reach of
    ``override_config``.
    """
    sorted_dir = config.SORTED_DIR if sorted_dir is None else sorted_dir
    browser_profile_dir = (
        config.PROJECT_DIR / _BROWSER_PROFILE_DIR_NAME if browser_profile_dir is None
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

    for source_dir in _iter_source_dirs(sorted_dir):
        source = source_dir.name
        strategy = strategies.get(source)

        for video in sorted(_iter_video_files(source_dir)):
            if strategy is None:
                result.no_scrape_strat += 1
                continue

            orient = video.relative_to(source_dir).parts[0]
            if orient not in ("landscape", "portrait"):
                continue

            output_path = sidecar_path(upscaled_video_path(source, orient, video.stem))
            if output_path.exists():
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

            write(output_path, payload)
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


def _failure_marker_path(output_path: Path) -> Path:
    """Sidecar marking a video whose scrape failed, so it is not retried every run.

    Delete this file to force a retry (e.g. after a transient failure is resolved).
    Kept separate from the JSON so it never confuses _is_t2v_provider in the upscale stage.
    """
    return output_path.with_name(output_path.name + ".failed")


def _write_failure_marker(output_path: Path, video: Path, error: BaseException) -> None:
    marker = _failure_marker_path(output_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{video.name}\n{error}\n", encoding="utf-8")


def _provider_image_url(video: Path, base_url: str) -> str:
    """The Provider image-page URL a video's stem maps to — its scrape entry point."""
    return f"{base_url}/image/{source_stem(video.stem)}"


def _iter_video_files(root: Path):
    yield from iter_finalized_videos(root, config.VIDEO_EXTENSIONS)


def _iter_source_dirs(root: Path):
    if not root.is_dir():
        return
    for p in sorted(root.iterdir()):
        if p.is_dir():
            yield p


def _scrape_provider_video(
    video_path: Path, image_url: str, browser: Path, base_url: str, profile_dir: Path,
) -> dict[str, str]:
    image_id = image_url.rstrip("/").split("/")[-1]
    candidate_urls = [
        image_url,
        f"{base_url}/video/{image_id}",
        f"{base_url}/text-to-video/{image_id}",
        f"{base_url}/image-to-video/{image_id}",
    ]

    video_prompt = ""
    source_image_url = ""
    video_metadata: dict[str, str] = {}
    for candidate in candidate_urls:
        html = fetch_dom(candidate, browser, profile_dir=profile_dir)
        document = parse_document(html)
        panel = query_selector(document, _CONTENT_PANEL_SELECTOR)
        if panel is not None:
            video_prompt = _extract_prompt_text(panel)
            source_image_url = _extract_source_image_url(panel, base_url)
            video_metadata = _extract_metadata_fields(document)
        if not video_prompt:
            embedded = _extract_provider_embedded_metadata(html, image_id)
            if embedded.prompt:
                video_prompt = embedded.prompt
                if not video_metadata:
                    video_metadata = _embedded_to_video_metadata(embedded)
                if embedded.parent_image_id and not source_image_url:
                    source_image_url = f"{base_url}/image/{embedded.parent_image_id}"
        if video_prompt:
            break
    if not video_prompt:
        raise RuntimeError(f"Could not extract Provider video prompt for {video_path.name}")

    video_data: dict[str, str] = {"prompt": video_prompt, **video_metadata}
    payload: dict[str, object] = {"video": video_data}

    if source_image_url:
        image_html = fetch_dom(source_image_url, browser, profile_dir=profile_dir)
        image_document = parse_document(image_html)
        image_panel = query_selector(image_document, _CONTENT_PANEL_SELECTOR)
        image_data: dict[str, str] = {}
        if image_panel is not None:
            pos = _extract_prompt_text(image_panel)
            neg = _extract_negative_prompt_text(image_panel)
            if pos:
                image_data["positive_prompt"] = pos
            if neg:
                image_data["negative_prompt"] = neg
            image_data.update(_extract_metadata_fields(image_document))
        else:
            image_id_str = source_image_url.rstrip("/").split("/")[-1]
            embedded = _extract_provider_embedded_metadata(image_html, image_id_str)
            if embedded.prompt:
                image_data["positive_prompt"] = embedded.prompt
            if embedded.negative_prompt:
                image_data["negative_prompt"] = embedded.negative_prompt
            image_data.update(_embedded_to_image_metadata(embedded))
        if image_data:
            payload["source_image"] = image_data
    return payload


def _build_strategies(browser, profile_dir):
    """Map each ingest source to a ``(video) -> payload`` metadata builder.

    Origenerator is a normal external content source whose metadata Evolver pulls
    from its own gallery database (see :mod:`tasks.origenerator_metadata`), so it
    needs no browser and is always available. Provider metadata is scraped from its
    website, so it registers only when a headless browser was found.
    """
    provider_source = config.PROVIDER_SOURCE
    base_url = config.PROVIDER_BASE_URL
    strategies = {"origenerator": origenerator_metadata.build_metadata}
    if browser is not None:
        strategies[provider_source] = lambda video: _scrape_provider_video(
            video, _provider_image_url(video, base_url), browser, base_url, profile_dir
        )
    return strategies


def _extract_prompt_text(panel: Node) -> str:
    """Extract the positive prompt text from a content panel.

    The prompt is the first text block inside a div > div structure that
    doesn't contain h2 labels (which would be metadata fields).
    """
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
    """Extract the negative prompt text from a content panel.

    The negative prompt is in a div with class 'max-h-80' that appears after
    a span/div containing 'Negative prompt'.
    """
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
    """Find the source image thumbnail img and derive the image page URL."""
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


# How wide a slice of the page around each mention of the id is read as the
# record for it. The embedded JSON is minified onto one line with everything
# else on the page, so there is no delimiter to stop at; 5,000 characters
# either side comfortably spans one record's fields without reaching the next
# item's on a listing page.
_JSON_WINDOW_CHARS = 5000

# Each field of the embedded record: what it is called on the dataclass, and
# how to read it out of a window. Every reader answers "" for absent, so the
# loop below has one shape rather than thirteen copies of it -- three of which
# differed only in converting an int, joining a pair, or reformatting a date.
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
    ("resolution", lambda blob: _resolution_field(blob)),
    ("quality", lambda blob: _extract_json_string_field(blob, "quality")),
    ("created", lambda blob: _created_field(blob)),
    ("action", lambda blob: _action_field(blob)),
    ("style", lambda blob: _extract_nullable_json_string_field(blob, "styleValue")),
    ("creativity", lambda blob: _int_field_as_text(blob, "creativity")),
)


def _extract_provider_embedded_metadata(html: str, page_id: str) -> _ProviderEmbeddedMetadata:
    """The record the page embeds for *page_id*, read out of the JSON around it.

    Each mention of the id is tried in turn, and each window twice -- once as
    it stands and once with the backslash-escaped quotes unescaped, because the
    same record appears both as JSON and as a JSON string holding JSON. The
    first mention that yields a prompt is taken to be the right one; a field
    already found is never overwritten by a later window.
    """
    found: dict[str, str] = {}
    for index in _all_indices(html, page_id):
        window = html[max(0, index - _JSON_WINDOW_CHARS): index + _JSON_WINDOW_CHARS]
        for candidate in (window, window.replace('\\"', '"')):
            for attribute, extract in _EMBEDDED_FIELDS:
                if not found.get(attribute):
                    found[attribute] = extract(candidate)
        if found.get("prompt"):
            break
    # By keyword, so a name in the table that no field answers to is a
    # TypeError here rather than a value silently going nowhere.
    return _ProviderEmbeddedMetadata(**found)


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
    """Title-case a Provider action, but keep the "pov" initialism fully upper.

    A plain ``str.title()`` would render "pov_gamma" as "Pov Gamma"; the
    library — and the backfill tool's spoken vocabulary — write it "POV Gamma",
    so one Fun Time filter query still reaches both producers' clips.
    """
    words = raw_action.replace("_", " ").split()
    return " ".join("POV" if word.lower() == "pov" else word.title() for word in words)


def _parse_provider_created_at(value: str) -> str:
    try:
        t = parsedate(value)
        if t is not None:
            return datetime.date(t[0], t[1], t[2]).isoformat()
    except Exception:
        pass
    return value


def _embedded_to_video_metadata(embedded: _ProviderEmbeddedMetadata) -> dict[str, str]:
    fields: dict[str, str] = {}
    if embedded.version:
        fields["model"] = f"Video {embedded.version}"
    elif embedded.model:
        fields["model"] = embedded.model
    for key, value in (
        ("action", embedded.action),
        ("resolution", embedded.resolution),
        ("aspect_ratio", embedded.aspect_ratio),
        ("quality", embedded.quality),
        ("seed", embedded.seed),
        ("created", embedded.created),
        ("style", embedded.style),
    ):
        if value:
            fields[key] = value
    return fields


def _embedded_to_image_metadata(embedded: _ProviderEmbeddedMetadata) -> dict[str, str]:
    fields: dict[str, str] = {}
    if embedded.model:
        fields["model"] = embedded.model
    for key, value in (
        ("action", embedded.action),
        ("resolution", embedded.resolution),
        ("aspect_ratio", embedded.aspect_ratio),
        ("quality", embedded.quality),
        ("seed", embedded.seed),
        ("created", embedded.created),
        ("style", embedded.style),
        ("creativity", embedded.creativity),
    ):
        if value:
            fields[key] = value
    return fields


_METADATA_LABELS = {
    "model", "action", "resolution", "aspect ratio", "quality",
    "seed", "created", "style", "creativity",
}


def _extract_metadata_fields(root: Node) -> dict[str, str]:
    fields: dict[str, str] = {}
    for label, value in extract_label_values(root, _METADATA_LABELS).items():
        key = label.replace(" ", "_")
        if key == "created":
            value = relative_dates.as_iso_date(value)
        fields[key] = value
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
