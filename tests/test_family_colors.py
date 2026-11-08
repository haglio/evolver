from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from shared_ui import palette

from tests.product_sources import strings_outside_docstrings

pytestmark = pytest.mark.repo_check

_ROOT = Path(__file__).resolve().parent.parent
_TREES = (_ROOT / "gui", _ROOT / "evolver", _ROOT / "backfill", _ROOT / "review_trash", _ROOT / "tasks",
          _ROOT / "util", _ROOT / "tools", _ROOT / "tests")

_HEX_NOT_TRIPLES_WHICH_PLAIN_FIXTURE_PIXELS_SHARE = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _family_hex() -> dict[str, str]:
    named: dict[str, list[str]] = {}
    for name in dir(palette):
        value = getattr(palette, name)
        if (name.isupper() and isinstance(value, tuple) and len(value) == 3
                and all(isinstance(channel, int) for channel in value)):
            named.setdefault(palette.as_hex(value), []).append(name)
    return {hexed: "/".join(sorted(names)) for hexed, names in named.items()}


def _sources() -> list[Path]:
    files = sorted(path for tree in _TREES if tree.is_dir()
                   for path in tree.rglob("*.py"))
    assert files, f"no modules found under {_ROOT}"
    return files


def test_no_color_here_or_in_the_tests_is_a_hand_copy_that_drifts_from_its_family_token():
    family = _family_hex()
    offenders = []
    for path in _sources():
        for node in strings_outside_docstrings(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.extend(
                f"{path.name}:{node.lineno} {found} is shared_ui.palette.{family[found.lower()]}"
                for found in _HEX_NOT_TRIPLES_WHICH_PLAIN_FIXTURE_PIXELS_SHARE.findall(node.value) if found.lower() in family)
    assert not offenders, (
        "a family color written out by hand instead of read from a shared_ui "
        "token: " + ", ".join(offenders))
