"""A small HTML parse-and-query library.

Grown inside the prompt scraper and extracted once it was, in substance, its
own module: a lenient DOM built on html.parser, a child-combinator CSS
selector (tag and class), text extraction, and the
label/value walk the scraped pages use (an ``<h2>`` label answered by the next
``<h1>`` sibling). Stdlib only; nothing here knows what a video is.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser


class Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Node] = []
        self.text_chunks: list[str] = []


class _DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs):
        node = Node(tag, {key: value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack.append(node)

    def handle_endtag(self, tag: str):
        if len(self.stack) > 1:
            self.stack.pop()

    def handle_startendtag(self, tag: str, attrs):
        node = Node(tag, {key: value or "" for key, value in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_data(self, data: str):
        self.stack[-1].text_chunks.append(data)


@dataclass
class _SelectorPart:
    tag: str
    classes: list[str]


def parse_document(html: str) -> Node:
    parser = _DocumentParser()
    parser.feed(html)
    return parser.root


def query_selector(root: Node, selector: str) -> Node | None:
    parts = [_parse_selector_part(part.strip()) for part in selector.split(">")]
    current = [root]
    for index, part in enumerate(parts):
        next_nodes: list[Node] = []
        for node in current:
            candidates = _descendants(node) if index == 0 else node.children
            for candidate in candidates:
                if _matches_selector_part(candidate, part):
                    next_nodes.append(candidate)
        if not next_nodes:
            return None
        current = next_nodes
    return current[0]


def text_content(node: Node) -> str:
    parts = list(node.text_chunks)
    for child in node.children:
        parts.append(text_content(child))
    return "".join(parts)


def find_all_by_tag(node: Node, tag: str):
    if node.tag == tag:
        yield node
    for child in node.children:
        yield from find_all_by_tag(child, tag)


def extract_label_values(root: Node, labels: set[str]) -> dict[str, str]:
    """The pages' metadata idiom: an ``<h2>`` label, then an ``<h1>`` value.

    Returns {lowercased label: value text} for every ``<h2>`` whose text is in
    *labels* and that has an ``<h1>`` among its later siblings.
    """
    fields: dict[str, str] = {}
    for h2 in find_all_by_tag(root, "h2"):
        label = text_content(h2).strip().lower()
        if label not in labels:
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
        fields[label] = text_content(h1).strip()
    return fields


def _descendants(node: Node):
    for child in node.children:
        yield child
        yield from _descendants(child)


def _parse_selector_part(raw: str) -> _SelectorPart:
    tag, _, classes = raw.partition(".")
    return _SelectorPart(tag=tag or "*", classes=[c for c in classes.split(".") if c])


def _matches_selector_part(node: Node, part: _SelectorPart) -> bool:
    if part.tag != "*" and node.tag != part.tag:
        return False
    classes = set(node.attrs.get("class", "").split())
    return all(required in classes for required in part.classes)
