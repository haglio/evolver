"""The two gates that hold the config seam open once it has been opened.

``config`` is a module-level singleton built at import from a git-ignored JSON
overlay, and every stage reaches into it rather than declaring what it needs.
Converting that is a ratchet, not a rewrite: each stage's ``run()`` grows
explicit keyword parameters, and the reads it used to make disappear one at a
time. Two numbers keep the ratchet honest.

``test_the_config_reference_count_matches_the_ledger`` holds the count of
``config.X`` references per unit *exactly*. Below the recorded number means a
conversion landed and the number was not lowered with it; above means a new
ambient read went in. Either way the build says so, which a ceiling calibrated
to today's worst value never could.

``test_the_overlay_keys_are_the_ones_the_contract_names`` holds the overlay's
key names, read out of the source rather than listed by hand. ``genau_source``
is shared byte-for-byte with origenerator, which reads the same key from its own
overlay, and the folder it names is the only thing that passes between the two
apps; the rest name a machine whose shape nobody here can see. A rename is a
silent break on somebody else's machine, so it fails here instead.
"""

import ast
import json
import unittest
from pathlib import Path

from tests.test_dead_code import PROJECT_ROOT, _source_files

# What each unit reads off the ambient ``config`` singleton today. Lower a
# number when a conversion removes reads. A number goes UP only for a read that
# nothing could reach becoming an ordinary one — a value a module bound at its
# own import is not counted here and cannot be redirected either, so moving it
# into ``config`` costs references and buys the seam; say which in the commit.
# Anything else that raises a number is a new ambient read, and the build stops
# it. The count comes from the syntax tree, so a mention in a comment or a
# docstring does not move it.
CONFIG_REFERENCE_LEDGER = {
    "tasks": 147,
    "util+backfill": 37,
    "gui": 14,
}

_UNITS = {
    "tasks": lambda name: name.startswith("tasks/") or name in (
        "evolver.py", "check_correspondence.py", "check_duplicate_sizes.py",
    ),
    "util+backfill": lambda name: name.startswith(("util/", "backfill/")),
    "gui": lambda name: name.startswith("gui/") or name in (
        "tray_app.py", "backfill_app.py",
    ),
}

# Every key the app reads out of the content overlay, as ``key`` or
# ``key.subkey``. ``genau_source`` is origenerator's too.
OVERLAY_KEYS = {
    "acts",
    "chrome_profile",
    "genau_source",
    "library_root",
    "project_roots",
    "retired_root",
    "scrape_provider",
    "scrape_provider.base_url",
    "scrape_provider.source",
}

# The two the overlay may leave out; both are documented as optional and both
# have a fallback, so the committed example does not carry them.
OPTIONAL_OVERLAY_KEYS = {"project_roots", "retired_root"}


def _config_references(tree: ast.AST) -> int:
    """How many times *tree* reaches into the ``config`` module.

    Counts ``config.X`` and any other load of the bare name, so
    ``getattr(config, name)`` cannot slip the ledger by spelling the read
    differently.
    """
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "config" and isinstance(node.ctx, ast.Load)
    )


class _OverlayKeys(ast.NodeVisitor):
    """The overlay keys one module reads, followed through the names it binds.

    ``load_content()`` returns the overlay mapping; a module either indexes it
    where it stands or parks it in a name first, and one that reads a nested
    group parks that too (``_PROVIDER = load_content()["scrape_provider"]``).
    So the names holding overlay data are collected as they are bound, and each
    one carries the path it was reached by. Keys read off a comprehension's
    target -- an ``acts`` entry's own fields -- are the element shape rather
    than the overlay's key names, and are not followed.
    """

    def __init__(self):
        # ``content`` is the parameter name config.py's two overlay-reading
        # helpers take their mapping as.
        self.paths: dict[str, str] = {"_CONTENT": "", "content": ""}
        self.keys: set[str] = set()
        # Overlay reads whose key this cannot see: a name, an f-string, a
        # comprehension target. One of those would put a key into the contract
        # with nothing recording it, so the gate refuses them rather than
        # quietly reading past them.
        self.unreadable: list[int] = []

    def _path_of(self, node: ast.AST) -> str | None:
        """The overlay path *node* evaluates to, or None if it is not overlay data."""
        if isinstance(node, ast.Name):
            return self.paths.get(node.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "load_content":
            return ""
        if isinstance(node, ast.Subscript):
            base = self._path_of(node.value)
            if base is None:
                return None
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                return f"{base}.{node.slice.value}".lstrip(".")
            self.unreadable.append(node.lineno)
        return None

    def visit_Assign(self, node: ast.Assign):
        path = self._path_of(node.value)
        if path is not None:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.paths[target.id] = path
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        path = self._path_of(node)
        if path:
            self.keys.add(path)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and node.args:
            base = self._path_of(func.value)
            if base is not None:
                key = node.args[0]
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    self.keys.add(f"{base}.{key.value}".lstrip("."))
                else:
                    self.unreadable.append(node.lineno)
        self.generic_visit(node)


def _trees() -> dict[str, ast.AST]:
    return {
        name: ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
        for name in _source_files(PROJECT_ROOT)
    }


class TestConfigSeam(unittest.TestCase):
    def test_the_config_reference_count_matches_the_ledger(self):
        counts = dict.fromkeys(CONFIG_REFERENCE_LEDGER, 0)
        unplaced = []
        for name, tree in _trees().items():
            references = _config_references(tree)
            if not references:
                continue
            for unit, belongs in _UNITS.items():
                if belongs(name):
                    counts[unit] += references
                    break
            else:
                unplaced.append(name)

        self.assertEqual(unplaced, [], "these modules belong to no unit, so nothing counts them")
        self.assertEqual(
            counts,
            CONFIG_REFERENCE_LEDGER,
            "lower the ledger in the commit that removes the reads; never raise it",
        )

    def test_the_overlay_keys_are_the_ones_the_contract_names(self):
        found: set[str] = set()
        unreadable: list[str] = []
        for name, tree in _trees().items():
            visitor = _OverlayKeys()
            visitor.visit(tree)
            found |= visitor.keys
            unreadable += [f"{name}:{line}" for line in visitor.unreadable]

        self.assertEqual(
            sorted(unreadable),
            [],
            "an overlay key spelled as anything but a literal is a key this "
            "gate cannot record; spell it out",
        )
        self.assertEqual(found, OVERLAY_KEYS)

    def test_the_committed_example_carries_every_required_key(self):
        """A public checkout loads the example, so a key missing from it is a
        ``KeyError`` at import for everyone who has no overlay of their own."""
        example = json.loads(
            Path(PROJECT_ROOT, "content.example.json").read_text(encoding="utf-8")
        )

        for key in sorted(OVERLAY_KEYS - OPTIONAL_OVERLAY_KEYS):
            with self.subTest(key=key):
                value = example
                for part in key.split("."):
                    self.assertIn(part, value)
                    value = value[part]


if __name__ == "__main__":
    unittest.main()
