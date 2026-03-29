"""Stage: scrape AI prompt metadata into mirrored JSON files."""

from __future__ import annotations

import csv
import datetime
import json
import logging
import re
import subprocess
import tempfile
from dataclasses import dataclass
from email.utils import parsedate
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import config
from tasks import bookmarks_sync
from tasks.purge_weird import source_stem
from util.media_files import iter_finalized_videos

log = logging.getLogger(__name__)

_CONTENT_PANEL_SELECTOR = r"main > div > div > div.flex-1.overflow-hidden > div.font-regular"
_provider_HOSTS = {"example.com", "www.example.com"}


@dataclass
class PromptScrapeResult:
    scraped: int = 0
    rescraped: int = 0
    skipped_existing: int = 0
    skipped_legacy: int = 0
    skipped_non_provider: int = 0
    missing_url: int = 0
    fetch_failures: int = 0
    source_missing: bool = False

    @property
    def ok(self) -> bool:
        return self.fetch_failures == 0


def run() -> PromptScrapeResult:
    result = PromptScrapeResult()
    log.info("=== Stage 5: scrape AI prompts ===")
    log.info("SOURCE CSV: %s", config.FUN_TIME_FAVS_FILE)
    log.info("PROMPTS DIR: %s", config.PROMPTS_DIR)

    path_to_url = _load_video_urls(result)
    if result.source_missing:
        log.info("Favorites CSV not found. Skipping prompt scrape.")
        return result

    browser = _find_browser_executable()
    if browser is None:
        result.fetch_failures += 1
        log.error("No supported browser executable found for prompt scraping.")
        return result

    for root in config.active_outbox_dirs():
        if not root.is_dir():
            continue
        for video in sorted(_iter_video_files(root)):
            output_path = _prompt_output_path(video, root)
            if output_path.exists():
                if not _is_legacy_format(output_path):
                    result.skipped_existing += 1
                    continue
                if result.rescraped >= config.RESCRAPE_BATCH_LIMIT:
                    result.skipped_legacy += 1
                    continue

            url = path_to_url.get(video.resolve())
            if url is None:
                url = _fallback_url_for_video(video)
            if url is None:
                result.missing_url += 1
                log.warning("No source URL found for: %s", video)
                continue

            parsed = urlparse(url)
            if parsed.netloc.lower() not in _provider_HOSTS:
                result.skipped_non_provider += 1
                continue

            is_rescrape = output_path.exists()
            try:
                payload = _scrape_provider_video(video, url, browser)
            except Exception:
                result.fetch_failures += 1
                log.exception("Prompt scrape failed for: %s", video)
                continue

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            if is_rescrape:
                result.rescraped += 1
                log.info("Rescrapped legacy prompts: %s", output_path)
            else:
                result.scraped += 1
                log.info("Wrote prompts: %s", output_path)

    log.info(
        "Stage 5 done. Scraped: %d, Rescrapped: %d, Existing skipped: %d, "
        "Legacy skipped: %d, Non-Provider skipped: %d, Missing URL: %d, Failures: %d",
        result.scraped,
        result.rescraped,
        result.skipped_existing,
        result.skipped_legacy,
        result.skipped_non_provider,
        result.missing_url,
        result.fetch_failures,
    )
    return result


def _load_video_urls(result: PromptScrapeResult) -> dict[Path, str]:
    path = config.FUN_TIME_FAVS_FILE
    if not path.is_file():
        result.source_missing = True
        return {}

    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        file_column = bookmarks_sync._file_column_name(list(reader.fieldnames or []))
        mapping: dict[Path, str] = {}
        for row in reader:
            raw_url = (row.get("web_url") or "").strip()
            url = bookmarks_sync._extract_url(raw_url)
            if url is None:
                continue
            if file_column:
                raw_file = (row.get(file_column) or "").strip()
                if raw_file:
                    mapping[_resolve_favorite_path(raw_file, path.parent)] = url
    return mapping


def _resolve_favorite_path(value: str, base_dir: Path) -> Path:
    match = bookmarks_sync._HYPERLINK_URL_RE.match(value)
    candidate = match.group(1) if match else value
    parsed = urlparse(candidate)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path.lstrip("/"))).resolve()

    path = Path(candidate)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _iter_video_files(root: Path):
    yield from iter_finalized_videos(root, config.VIDEO_EXTENSIONS)


def _is_legacy_format(json_path: Path) -> bool:
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        return "video" not in payload
    except Exception:
        return False


def _prompt_output_path(video_path: Path, outbox_root: Path) -> Path:
    return config.PROMPTS_DIR / outbox_root.name / video_path.relative_to(outbox_root).with_suffix(".json")


def _fallback_url_for_video(video_path: Path) -> str | None:
    stem = source_stem(video_path.stem)
    source_name = next((part.lower() for part in video_path.parts if part.lower() in {"provider", "provider2"}), "")
    if source_name == "provider":
        return f"https://example.com/image/{stem}"
    return None


def _scrape_provider_video(video_path: Path, image_url: str, browser: Path) -> dict[str, str]:
    image_id = image_url.rstrip("/").split("/")[-1]
    candidate_urls = [
        image_url,
        f"https://example.com/video/{image_id}",
        f"https://example.com/text-to-video/{image_id}",
        f"https://example.com/image-to-video/{image_id}",
    ]

    video_prompt = ""
    source_image_url = ""
    video_metadata: dict[str, str] = {}
    for candidate in candidate_urls:
        html = _fetch_dom(candidate, browser)
        document = _parse_html_document(html)
        panel = _query_selector(document, _CONTENT_PANEL_SELECTOR)
        if panel is not None:
            video_prompt = _extract_prompt_text(panel)
            source_image_url = _extract_source_image_url(panel)
            video_metadata = _extract_metadata_fields(document)
        if not video_prompt:
            embedded = _extract_provider_embedded_metadata(html, image_id)
            if embedded.prompt:
                video_prompt = embedded.prompt
                if not video_metadata:
                    video_metadata = _embedded_to_video_metadata(embedded)
                if embedded.parent_image_id and not source_image_url:
                    source_image_url = f"https://example.com/image/{embedded.parent_image_id}"
        if video_prompt:
            break
    if not video_prompt:
        raise RuntimeError(f"Could not extract Provider video prompt for {video_path.name}")

    video_data: dict[str, str] = {"prompt": video_prompt, **video_metadata}
    payload: dict[str, object] = {"video": video_data}

    if source_image_url:
        image_html = _fetch_dom(source_image_url, browser)
        image_document = _parse_html_document(image_html)
        image_panel = _query_selector(image_document, _CONTENT_PANEL_SELECTOR)
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


def _extract_prompt_text(panel: _Node) -> str:
    """Extract the positive prompt text from a content panel.

    The prompt is the first text block inside a div > div structure that
    doesn't contain h2 labels (which would be metadata fields).
    """
    for child in panel.children:
        if child.tag != "div":
            continue
        inner_divs = [c for c in child.children if c.tag == "div"]
        if len(inner_divs) == 1:
            text = _text_content(inner_divs[0]).strip()
            has_h2 = any(True for _ in _find_all_by_tag(inner_divs[0], "h2"))
            if text and not has_h2:
                return text
    return ""


def _extract_negative_prompt_text(panel: _Node) -> str:
    """Extract the negative prompt text from a content panel.

    The negative prompt is in a div with class 'max-h-80' that appears after
    a span/div containing 'Negative prompt'.
    """
    found_label = False
    for child in panel.children:
        if not found_label:
            text = _text_content(child).strip().lower()
            if "negative prompt" in text and "max-h-80" not in child.attrs.get("class", ""):
                found_label = True
                continue
        if found_label and "max-h-80" in child.attrs.get("class", ""):
            return _text_content(child).strip()
    return ""


def _extract_source_image_url(panel: _Node) -> str:
    """Find the source image thumbnail img and derive the image page URL."""
    for img in _find_all_by_tag(panel, "img"):
        src = img.attrs.get("src", "")
        if src:
            return _image_page_url_from_src(src)
    return ""


def _image_page_url_from_src(src: str) -> str:
    parsed = urlparse(src)
    image_id = parsed.path.strip("/").split("/")[-1]
    if not image_id:
        return ""
    return f"https://example.com/image/{image_id}"


def _fetch_dom(url: str, browser: Path) -> str:
    profile_dir = config.PROJECT_DIR / ".tmp-prompt-browser-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--disable-breakpad",
            "--disable-crash-reporter",
            "--no-first-run",
            f"--user-data-dir={profile_dir}",
            "--virtual-time-budget=10000",
            "--dump-dom",
            url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"Browser DOM dump failed for {url}: {stderr}")
    return proc.stdout


def _find_browser_executable() -> Path | None:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: "_Node | None" = None):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node] = []
        self.text_chunks: list[str] = []


class _DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs):
        node = _Node(tag, {key: value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack.append(node)

    def handle_endtag(self, tag: str):
        if len(self.stack) > 1:
            self.stack.pop()

    def handle_startendtag(self, tag: str, attrs):
        node = _Node(tag, {key: value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_data(self, data: str):
        self.stack[-1].text_chunks.append(data)


@dataclass
class _SelectorPart:
    tag: str
    classes: list[str]
    nth_child: int | None = None


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


def _parse_html_document(html: str) -> _Node:
    parser = _DocumentParser()
    parser.feed(html)
    return parser.root


def _query_selector(root: _Node, selector: str) -> _Node | None:
    parts = [_parse_selector_part(part.strip()) for part in selector.split(">")]
    current = [root]
    for index, part in enumerate(parts):
        next_nodes: list[_Node] = []
        for node in current:
            candidates = _descendants(node) if index == 0 else node.children
            for candidate in candidates:
                if _matches_selector_part(candidate, part):
                    next_nodes.append(candidate)
        if not next_nodes:
            return None
        current = next_nodes
    return current[0]


def _descendants(node: _Node):
    for child in node.children:
        yield child
        yield from _descendants(child)


def _parse_selector_part(raw: str) -> _SelectorPart:
    nth_child = None
    match = re.search(r":nth-child\((\d+)\)", raw)
    if match:
        nth_child = int(match.group(1))
        raw = raw[:match.start()] + raw[match.end():]

    bits = _split_selector_token(raw)
    tag = bits[0] or "*"
    classes = [_unescape_css_name(bit) for bit in bits[1:] if bit]
    return _SelectorPart(tag=tag, classes=classes, nth_child=nth_child)


def _unescape_css_name(value: str) -> str:
    return re.sub(r"\\(.)", r"\1", value)


def _split_selector_token(raw: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in raw:
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            current.append(char)
            escaped = True
            continue
        if char == ".":
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _matches_selector_part(node: _Node, part: _SelectorPart) -> bool:
    if part.tag != "*" and node.tag != part.tag:
        return False
    classes = set(node.attrs.get("class", "").split())
    if any(required not in classes for required in part.classes):
        return False
    if part.nth_child is not None:
        parent = node.parent
        if parent is None:
            return False
        position = parent.children.index(node) + 1
        if position != part.nth_child:
            return False
    return True


def _text_content(node: _Node) -> str:
    parts = list(node.text_chunks)
    for child in node.children:
        parts.append(_text_content(child))
    return "".join(parts)


def _extract_provider_embedded_metadata(html: str, page_id: str) -> _ProviderEmbeddedMetadata:
    metadata = _ProviderEmbeddedMetadata()
    for index in _all_indices(html, page_id):
        window = html[max(0, index - 5000): index + 5000]
        for candidate in (window, window.replace('\\"', '"')):
            if not metadata.prompt:
                metadata.prompt = _extract_json_string_field(candidate, "prompt")
            if not metadata.negative_prompt:
                metadata.negative_prompt = _extract_nullable_json_string_field(candidate, "negative_prompt")
            if not metadata.parent_image_id:
                metadata.parent_image_id = _extract_nullable_json_string_field(candidate, "parent_image_id")
            if not metadata.model:
                metadata.model = _extract_json_string_field(candidate, "model")
            if not metadata.version:
                metadata.version = _extract_json_string_field(candidate, "version")
            if not metadata.seed:
                seed_int = _extract_json_int_field(candidate, "seed")
                if seed_int is not None:
                    metadata.seed = str(seed_int)
            if not metadata.aspect_ratio:
                metadata.aspect_ratio = _extract_json_string_field(candidate, "aspectRatio")
            if not metadata.resolution:
                width = _extract_json_int_field(candidate, "width")
                height = _extract_json_int_field(candidate, "height")
                if width is not None and height is not None:
                    metadata.resolution = f"{width}x{height}"
            if not metadata.quality:
                metadata.quality = _extract_json_string_field(candidate, "quality")
            if not metadata.created:
                created_at = _extract_json_string_field(candidate, "createdAt")
                if created_at:
                    metadata.created = _parse_provider_created_at(created_at)
            if not metadata.action:
                raw_action = _extract_json_first_array_string(candidate, "action")
                if raw_action:
                    metadata.action = raw_action.replace("_", " ").title()
            if not metadata.style:
                metadata.style = _extract_nullable_json_string_field(candidate, "styleValue")
            if not metadata.creativity:
                creativity_int = _extract_json_int_field(candidate, "creativity")
                if creativity_int is not None:
                    metadata.creativity = str(creativity_int)
        if metadata.prompt:
            break
    return metadata


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


def _extract_metadata_fields(root: _Node) -> dict[str, str]:
    fields: dict[str, str] = {}
    for h2 in _find_all_by_tag(root, "h2"):
        label = _text_content(h2).strip().lower()
        if label not in _METADATA_LABELS:
            continue
        parent = h2.parent
        if parent is None:
            continue
        siblings = parent.children
        try:
            h2_index = siblings.index(h2)
        except ValueError:
            continue
        h1 = next((c for c in siblings[h2_index + 1:] if c.tag == "h1"), None)
        if h1 is None:
            continue
        key = label.replace(" ", "_")
        value = _text_content(h1).strip()
        if key == "created":
            value = _parse_relative_date(value)
        fields[key] = value
    return fields


def _find_all_by_tag(node: _Node, tag: str):
    if node.tag == tag:
        yield node
    for child in node.children:
        yield from _find_all_by_tag(child, tag)


def _today() -> datetime.date:
    return datetime.date.today()


_RELATIVE_DATE_RE = re.compile(r"^(\d+)(mo|[mhdw])\s+ago$", re.IGNORECASE)


def _parse_relative_date(value: str) -> str:
    match = _RELATIVE_DATE_RE.match(value.strip())
    if not match:
        return value
    amount = int(match.group(1))
    unit = match.group(2).lower()
    today = _today()
    if unit == "m" or unit == "h":
        return today.isoformat()
    if unit == "d":
        return (today - datetime.timedelta(days=amount)).isoformat()
    if unit == "w":
        return (today - datetime.timedelta(weeks=amount)).isoformat()
    if unit == "mo":
        month = today.month - amount
        year = today.year
        while month < 1:
            month += 12
            year -= 1
        day = min(today.day, _days_in_month(year, month))
        return datetime.date(year, month, day).isoformat()
    return value


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)).day


def _all_indices(haystack: str, needle: str) -> list[int]:
    indices: list[int] = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index == -1:
            return indices
        indices.append(index)
        start = index + len(needle)
