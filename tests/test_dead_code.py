"""Dead-code detection.

Parses every source file with ``ast`` to collect function / method
definitions, then checks that each name appears as a ``Name`` or
``Attribute`` reference somewhere in the codebase (source + tests).

Names invoked only by external frameworks (Qt virtual overrides,
HTMLParser hooks, entry points) live in ``_FRAMEWORK_OVERRIDES``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# ── False-positive whitelist ──────────────────────────────────────────
# Names called by frameworks / the OS, not by our Python code.
_FRAMEWORK_OVERRIDES: frozenset[str] = frozenset({
    # Qt virtual-method overrides (called by the event loop)
    "paintEvent",
    "mousePressEvent",
    "closeEvent",
    "sizeHint",
    "drawFocus",
    "accept",  # QDialog.accept
    # Python HTMLParser overrides
    "handle_starttag",
    "handle_endtag",
    "handle_startendtag",
    "handle_data",
    # Script entry points (invoked by __main__ guard)
    "main",
})


# ── Helpers ───────────────────────────────────────────────────────────


def _src_files() -> list[Path]:
    """Non-test .py source files."""
    return sorted(
        p
        for p in _ROOT.rglob("*.py")
        if not p.name.startswith("test_")
        and "tests" not in p.relative_to(_ROOT).parts
        and p.name != "conftest.py"
    )


def _all_py() -> list[Path]:
    """Every .py in the repo (source + tests)."""
    return list(_ROOT.rglob("*.py"))


def _defined_names(path: Path) -> list[str]:
    """Function and method names defined in *path*."""
    tree = ast.parse(path.read_text("utf-8"), str(path))
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _referenced_names() -> frozenset[str]:
    """All names appearing as ``Name.id`` or ``Attribute.attr``."""
    refs: set[str] = set()
    for p in _all_py():
        tree = ast.parse(p.read_text("utf-8"), str(p))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                refs.add(node.id)
            elif isinstance(node, ast.Attribute):
                refs.add(node.attr)
    return frozenset(refs)


# ── Test ──────────────────────────────────────────────────────────────


def test_no_dead_functions():
    """Every defined function or method must be referenced somewhere."""
    refs = _referenced_names()
    dead: list[str] = []

    for path in _src_files():
        rel = path.relative_to(_ROOT)
        for name in _defined_names(path):
            if name.startswith("__") and name.endswith("__"):
                continue
            if name in _FRAMEWORK_OVERRIDES:
                continue
            if name not in refs:
                dead.append(f"  {rel}: {name}")

    assert not dead, (
        "Defined but never referenced — delete or whitelist:\n"
        + "\n".join(sorted(dead))
    )
