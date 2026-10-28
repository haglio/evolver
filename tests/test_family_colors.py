"""No color here is a hand-typed copy of one the family already owns.

`shared_ui.colors` carries the family's palette and `shared_ui.palette` is the
same list without Qt; a hex literal whose value is one of those tokens is a
second copy of a number that has one home.  It drifts: Fun Time's reference page
mirrored seven of them by hand and its border ended up three points off the
token it was copied from.

The tests are walked as well as the source, because that is where this repo's
copies were -- a run's green check asserted as ``"#30a030"`` goes red the day
the family's green moves, over a window that is drawing exactly what it should.
``status_symbols`` already answers with the token, so the assertion can too.

Only hex literals are checked.  ``(255, 255, 255)`` is white to anything that
draws, and refusing every triple that happens to equal a token would refuse
plain white pixels in a fixture.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from shared_ui import palette

from tests.product_sources import strings_outside_docstrings

pytestmark = pytest.mark.repo_check

_ROOT = Path(__file__).resolve().parent.parent
_TREES = (_ROOT / "gui", _ROOT / "evolver", _ROOT / "backfill", _ROOT / "review_weird", _ROOT / "tasks",
          _ROOT / "util", _ROOT / "tools", _ROOT / "tests")

# "#abc" and "#aabbcc" -- how a color reaches a Qt stylesheet or an HTML label
# when it did not come from a token.
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _family_hex() -> dict[str, str]:
    """Every shared_ui token's ``#rrggbb``, and the names that spell it."""
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


def test_no_color_here_is_a_hand_copy_of_a_family_token():
    # Parsed rather than grepped, so a "#" in a comment or a path is not a hit --
    # only text the app actually paints with, or a test asserts on.
    family = _family_hex()
    offenders = []
    for path in _sources():
        for node in strings_outside_docstrings(ast.parse(path.read_text(encoding="utf-8"))):
            for found in _HEX.findall(node.value):
                if found.lower() in family:
                    offenders.append(
                        f"{path.name}:{node.lineno} {found} is "
                        f"shared_ui.palette.{family[found.lower()]}")
    assert not offenders, (
        "a family color written out by hand instead of read from a shared_ui "
        "token: " + ", ".join(offenders))
