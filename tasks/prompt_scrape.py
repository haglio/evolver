"""Stage: scrape AI prompt metadata into mirrored JSON files."""

from __future__ import annotations

import csv
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

import config
from tasks import bookmarks_sync
from tasks.purge_weird import source_stem

log = logging.getLogger(__name__)

_VIDEO_PROMPT_SELECTOR = (
    r"body > div:nth-child(40) > div.relative.flex.h-full.min-h-screen.flex-col > main > "
    r"div > div.mt-2.w-full.max-w-full.gap-x-2.rounded-sm.p-2 > div.flex-1.overflow-hidden > "
    r"div.font-regular.selection\:bg-primary > div:nth-child(2) > div"
)
_SOURCE_IMAGE_THUMB_SELECTOR = (
    r"body > div:nth-child(40) > div.relative.flex.h-full.min-h-screen.flex-col > main > "
    r"div > div.mt-2.w-full.max-w-full.gap-x-2.rounded-sm.p-2 > div.flex-1.overflow-hidden > "
    r"div.font-regular.selection\:bg-primary > div.-mt-4.px-2.pb-4 > "
    r"div.h-25.w-fit.cursor-pointer.rounded-xl.border.border-\[\#151515\].bg-transparent.p-2."
    r"text-white.transition-all.duration-200.ease-in-out.will-change-transform.hover\:bg-\[\#0e0e0e\]."
    r"active\:scale-\[0\.95\].active\:border-\[\#303030\].active\:bg-\[\#171717\] > img"
)
_IMAGE_POSITIVE_PROMPT_SELECTOR = (
    r"body > div:nth-child(42) > div.relative.flex.h-full.min-h-screen.flex-col > main > "
    r"div > div.mt-2.w-full.max-w-full.gap-x-2.rounded-sm.p-2 > div.flex-1.overflow-hidden > "
    r"div.font-regular.selection\:bg-primary > div:nth-child(2) > div"
)
_IMAGE_NEGATIVE_PROMPT_SELECTOR = (
    r"body > div:nth-child(42) > div.relative.flex.h-full.min-h-screen.flex-col > main > "
    r"div > div.mt-2.w-full.max-w-full.gap-x-2.rounded-sm.p-2 > div.flex-1.overflow-hidden > "
    r"div.font-regular.selection\:bg-primary > div.max-h-80.overflow-y-auto.rounded-sm."
    r"p-2.text-\[\#fefefe\]"
)
_HYPERLINK_URL_RE = re.compile(r'^=HYPERLINK\("([^"]+)"[;,]', re.IGNORECASE)
_provider_HOSTS = {"example.com", "www.example.com"}


@dataclass
class PromptScrapeResult:
    scraped: int = 0
    skipped_existing: int = 0
    skipped_non_provider: int = 0
    missing_url: int = 0
    fetch_failures: int = 0
    source_missing: bool = False

    @property
    def ok(self) -> bool:
        return self.fetch_failures == 0


def run() -> PromptScrapeResult:
    result = PromptScrapeResult()
    log.info("=== Stage 4: scrape AI prompts ===")
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
                result.skipped_existing += 1
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

            try:
                payload = _scrape_provider_video(video, url, browser)
            except Exception:
                result.fetch_failures += 1
                log.exception("Prompt scrape failed for: %s", video)
                continue

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            result.scraped += 1
            log.info("Wrote prompts: %s", output_path)

    log.info(
        "Stage 4 done. Scraped: %d, Existing skipped: %d, Non-Provider skipped: %d, Missing URL: %d, Failures: %d",
        result.scraped,
        result.skipped_existing,
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
            url = _extract_url(raw_url)
            if url is None:
                continue
            if file_column:
                raw_file = (row.get(file_column) or "").strip()
                if raw_file:
                    mapping[_resolve_favorite_path(raw_file, path.parent)] = url
    return mapping


def _resolve_favorite_path(value: str, base_dir: Path) -> Path:
    match = _HYPERLINK_URL_RE.match(value)
    candidate = match.group(1) if match else value
    parsed = urlparse(candidate)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path.lstrip("/"))).resolve()

    path = Path(candidate)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _extract_url(value: str) -> str | None:
    match = _HYPERLINK_URL_RE.match(value)
    candidate = match.group(1) if match else value
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


def _iter_video_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in config.VIDEO_EXTENSIONS:
            yield path


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
    for candidate in candidate_urls:
        html = _fetch_dom(candidate, browser)
        document = _parse_html_document(html)
        prompt_node = _query_selector(document, _VIDEO_PROMPT_SELECTOR)
        if prompt_node is not None:
            video_prompt = _text_content(prompt_node).strip()
            thumb = _query_selector(document, _SOURCE_IMAGE_THUMB_SELECTOR)
            if thumb is not None:
                source_image_url = _image_page_url_from_src(thumb.attrs.get("src", ""))
            break
        embedded = _extract_provider_embedded_metadata(html, image_id)
        if embedded.prompt:
            video_prompt = embedded.prompt
            if embedded.parent_image_id:
                source_image_url = f"https://example.com/image/{embedded.parent_image_id}"
            break
    if not video_prompt:
        raise RuntimeError(f"Could not extract Provider video prompt for {video_path.name}")

    payload = {"video_prompt": video_prompt}
    if source_image_url:
        image_html = _fetch_dom(source_image_url, browser)
        image_document = _parse_html_document(image_html)
        positive_node = _query_selector(image_document, _IMAGE_POSITIVE_PROMPT_SELECTOR)
        negative_node = _query_selector(image_document, _IMAGE_NEGATIVE_PROMPT_SELECTOR)
        embedded = _extract_provider_embedded_metadata(image_html, source_image_url.rstrip("/").split("/")[-1])
        if positive_node is not None:
            payload["source_image_positive_prompt"] = _text_content(positive_node).strip()
        elif embedded.prompt:
            payload["source_image_positive_prompt"] = embedded.prompt
        if negative_node is not None:
            payload["source_image_negative_prompt"] = _text_content(negative_node).strip()
        elif embedded.negative_prompt:
            payload["source_image_negative_prompt"] = embedded.negative_prompt
    return payload


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
            prompt = _extract_json_string_field(candidate, "prompt")
            if prompt and not metadata.prompt:
                metadata.prompt = prompt
            negative_prompt = _extract_nullable_json_string_field(candidate, "negative_prompt")
            if negative_prompt and not metadata.negative_prompt:
                metadata.negative_prompt = negative_prompt
            parent_image_id = _extract_nullable_json_string_field(candidate, "parent_image_id")
            if parent_image_id and not metadata.parent_image_id:
                metadata.parent_image_id = parent_image_id
        if metadata.prompt and (metadata.parent_image_id or metadata.negative_prompt):
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


def _all_indices(haystack: str, needle: str) -> list[int]:
    indices: list[int] = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index == -1:
            return indices
        indices.append(index)
        start = index + len(needle)
