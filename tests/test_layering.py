"""Which packages may import which, held by the imports rather than by care.

The repo's layering is ``util <- tasks <- evolver <- gui <- tray_app``: the
stages reach the library through util, the orchestrator sequences the stages,
and the window layer reaches the stages only through the orchestrator. It is
the invariant that makes "the pipeline is what touches the library" true, and
it was broken by one line -- ``gui/app.py`` importing ``tasks.nonai_upscale``
to suspend a detached ffmpeg from a twenty-second GUI timer, outside any
pipeline run, with no stage record and no run record.

Nothing said so, and nothing could: an upward import is ordinary Python and
raises nothing. So the edges are listed, and held as an equality. A new one
fails here; an edge nobody uses any more fails too, and is lowered in the
commit that removed it.
"""

import ast
import unittest
from pathlib import Path

from tests.product_sources import PROJECT_ROOT, product_sources

# Every package and root module of this checkout, so an import of one can be
# told from an import of a third-party library or the standard one.
_OURS = (
    "backfill", "backfill_app", "check_correspondence", "check_duplicate_sizes",
    "config", "content_overlay", "evolver", "gui", "preview_branch", "tasks",
    "tray_app", "util", "vulture_whitelist",
)

# What each may import. ``gui`` may reach exactly one thing under ``tasks``:
# tasks/stages.py, the stage registry, which sits with the stage
# implementations so the headless CLI can read it and which the two windows
# read their labels, tooltips and band colours out of. Not a stage.
ALLOWED = {
    "backfill": {"config", "content_overlay", "util"},
    "backfill_app": {"backfill", "evolver"},
    "check_correspondence": {"config", "util"},
    "check_duplicate_sizes": {"config", "util"},
    "config": {"content_overlay"},
    "evolver": {"check_correspondence", "check_duplicate_sizes", "config",
                "tasks", "util"},
    "gui": {"config", "evolver", "tasks.stages", "util"},
    # The branch preview assembles a window out of the stages' reads without
    # running any of them, so it reaches both layers at once -- the one place
    # that is allowed, and only because it is an entry point of its own that
    # the app never imports.
    "preview_branch": {"config", "evolver", "gui", "tasks", "util"},
    "tasks": {"config", "util"},
    "tray_app": {"gui", "util"},
    "util": {"config"},
}


def _package_of(dotted: str) -> str | None:
    head = dotted.split(".", maxsplit=1)[0]
    return head if head in _OURS else None


def _imports(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def _edges() -> tuple[dict[str, set[str]], list[str]]:
    """Which allowed edge each import used, and every import that used none."""
    used: dict[str, set[str]] = {}
    unlisted: list[str] = []
    for name in product_sources(PROJECT_ROOT):
        source = _package_of(name.replace("/", ".").removesuffix(".py"))
        if source is None:
            continue
        tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
        for imported in _imports(tree):
            if _package_of(imported) in (None, source):
                continue
            allowed = ALLOWED.get(source, set())
            match = next(
                (prefix for prefix in allowed
                 if imported == prefix or imported.startswith(prefix + ".")),
                None,
            )
            if match is None:
                unlisted.append(f"{name}: {imported}")
            else:
                used.setdefault(source, set()).add(match)
    return used, unlisted


class TestLayering(unittest.TestCase):
    def test_no_package_imports_one_it_is_not_allowed_to(self):
        _used, unlisted = _edges()

        self.assertEqual(
            sorted(unlisted),
            [],
            "an import across a layer boundary that nothing declares -- either "
            "it belongs in ALLOWED with a reason, or it is the wrong way round",
        )

    def test_every_declared_edge_is_one_something_actually_uses(self):
        """A dependency that has gone is a smaller surface, and the list has to
        say so -- otherwise it drifts into describing a shape nothing has."""
        used, _unlisted = _edges()

        self.assertEqual(used, ALLOWED)


if __name__ == "__main__":
    unittest.main()
