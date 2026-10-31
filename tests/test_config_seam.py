"""The gates that hold the config seam open once it has been opened.

``config`` is a module-level singleton built at import from a git-ignored JSON
overlay, and every stage reaches into it rather than declaring what it needs.
Converting that is a ratchet, not a rewrite: each stage's ``run()`` grows
explicit keyword parameters, and the reads it used to make disappear one at a
time.
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

import pytest

from tests.product_sources import PROJECT_ROOT, product_sources

pytestmark = pytest.mark.repo_check

CONFIG_REFERENCE_CEILINGS = {
    "backfill/decisions.py": 2,
    "backfill/queue.py": 2,
    "backfill/thumbnails.py": 3,
    "backfill/voice.py": 4,
    "check_correspondence.py": 6,
    "check_duplicate_sizes.py": 4,
    "evolver.py": 10,
    "gui/app.py": 4,
    "gui/branch_session.py": 6,
    "gui/main_window.py": 2,
    "gui/peer_watch.py": 1,
    "gui/presence_throttle.py": 1,
    "gui/process_identity.py": 2,
    "gui/run_record.py": 1,
    "gui/run_controller.py": 2,
    "gui/settings.py": 2,
    "gui/startup.py": 1,
    "gui/tray.py": 1,
    "gui/worker.py": 1,
    "review_weird/window.py": 1,
    "tasks/bookmarks_sync.py": 4,
    "tasks/clip_scripts.py": 1,
    "tasks/genau_deliver.py": 5,
    "tasks/nonai_encode.py": 9,
    "tasks/nonai_files.py": 7,
    "tasks/nonai_group.py": 1,
    "tasks/nonai_queue.py": 2,
    "tasks/nonai_upscale.py": 1,
    "tasks/origenerator_downtime.py": 1,
    "tasks/prompt_scrape.py": 6,
    "tasks/provenance_sweep.py": 1,
    "tasks/reference_sync.py": 2,
    "tasks/scene_scripts.py": 1,
    "tasks/scripts_sync.py": 8,
    "tasks/sort.py": 3,
    "tasks/stages.py": 1,
    "tasks/stray_files.py": 9,
    "tasks/upscale.py": 14,
    "tasks/video_types.py": 6,
    "tasks/watch_weights.py": 5,
    "tasks/withdrawn.py": 7,
    "util/lanes.py": 9,
    "util/origenerator_gallery.py": 2,
    "util/preview.py": 2,
    "util/script_library.py": 6,
    "util/media_files.py": 3,
    "util/nonai_library.py": 4,
    "util/contract.py": 4,
    "util/nonai_retire.py": 1,
    "util/reference_stores.py": 4,
    "util/sidecar.py": 6,
    "util/topaz.py": 3,
    "util/video_locator.py": 2,
    "util/warm_gun.py": 4,
    "util/weird_piles.py": 9,
}

# Every key the app reads out of the content overlay, as ``key`` or
# ``key.subkey``.
OVERLAY_KEYS = {
    "acts",
    "cameras",
    "chrome_profile",
    "curated_examples",
    "display_timezone",
    "excerpt_folders",
    "retired_root",
    "scrape_provider",
    "scrape_provider.base_url",
    "scrape_provider.source",
    "topaz_ffmpeg",
    "topaz_models",
    "version_overrides",
    "vr_videos",
    "warm_gun_outbox",
}

# The ones the overlay may leave out; each is documented as optional and each
# has a fallback, so the committed example does not carry them. The two Topaz
# paths are absent for a second reason: the fallback is where the installer
# puts them, and an example naming one machine's install would read as the
# answer rather than as the override it is.
OPTIONAL_OVERLAY_KEYS = {
    "display_timezone", "retired_root", "topaz_ffmpeg",
    "topaz_models", "version_overrides", "vr_videos", "warm_gun_outbox",
}


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


def _config_imports(tree: ast.AST) -> list[int]:
    """Lines importing ``config`` as anything but the plain module name.

    The ledger counts loads of the name ``config``, so ``from config import X``
    reaches the same singleton and scores zero — a new ambient read that lands
    green, and a way to "convert" a module by rewriting its import while
    lowering its number. Neither spelling exists in the tree; the point of
    refusing them is that the seam is opened by a parameter, not by a different
    way of saying the same import.
    """
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "config":
            lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            lines += [node.lineno for a in node.names if a.name == "config" and a.asname]
    return lines


def _import_time_config_defaults(tree: ast.AST) -> list[int]:
    """Lines where a signature default is read off ``config``.

    The one rule the whole seam rests on. ``def run(*, x=config.X)`` is
    evaluated once, when the module is imported, so the value is frozen before
    anything can redirect it and ``override_config`` — which every stage test
    steers with — cannot reach it. The sentinel form
    (``x=None`` then ``x = config.X if x is None else x``) reads at call time.
    Both spellings hold the same ``config.X``, so the count cannot tell them
    apart and this does.
    """
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is None:
                continue
            lines += [
                default.lineno
                for inner in ast.walk(default)
                if isinstance(inner, ast.Name) and inner.id == "config"
            ]
    return lines


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

    def __init__(self, prebound: dict[str, str] | None = None):
        # Only config.py starts with names already holding overlay data —
        # ``_CONTENT`` and the ``content`` parameter its two helpers take their
        # mapping as. Seeding those everywhere would harvest the literal keys of
        # any unrelated dict a module happened to call ``content``.
        self.paths: dict[str, str] = dict(prebound or {})
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
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "overlay_value" and node.args):
            # app_support.overlay.overlay_value(<overlay>, "key", "subkey", ...):
            # the named read, which refuses by name where a subscript would
            # raise a bare KeyError; the keys are its positional arguments.
            base = self._path_of(node.args[0])
            if base is None:
                return None
            keys = node.args[1:]
            if all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in keys):
                return ".".join([base, *(key.value for key in keys)]).lstrip(".")
            self.unreadable.append(node.lineno)
            return None
        if isinstance(node, ast.Subscript):
            base = self._path_of(node.value)
            if base is None:
                return None
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                return f"{base}.{node.slice.value}".lstrip(".")
            self.unreadable.append(node.lineno)
        return None

    def _bind(self, target: ast.AST, value: ast.AST) -> None:
        path = self._path_of(value)
        if path is not None and isinstance(target, ast.Name):
            self.paths[target.id] = path

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            self._bind(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.value is not None:
            self._bind(node.target, node.value)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr):
        self._bind(node.target, node.value)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        path = self._path_of(node)
        if path:
            self.keys.add(path)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id == "overlay_value":
            path = self._path_of(node)
            if path:
                self.keys.add(path)
        if isinstance(func, ast.Attribute) and (base := self._path_of(func.value)) is not None:
            # ``get`` is the one call this can read a key out of. Every other
            # method on the mapping — ``pop``, ``setdefault``, ``keys`` — either
            # names a key it would have to know about or ranges over all of
            # them, so it is refused rather than read past.
            key = node.args[0] if node.args else None
            if func.attr == "get" and isinstance(key, ast.Constant) and isinstance(key.value, str):
                self.keys.add(f"{base}.{key.value}".lstrip("."))
            else:
                self.unreadable.append(node.lineno)
        self.generic_visit(node)


def _trees() -> dict[str, ast.AST]:
    return {
        name: ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
        for name in product_sources(PROJECT_ROOT)
    }


class TestConfigSeam(unittest.TestCase):
    def test_no_module_reads_config_more_often_than_its_ceiling(self):
        over = {
            name: f"{references} reads, ceiling {CONFIG_REFERENCE_CEILINGS.get(name, 0)}"
            for name, tree in _trees().items()
            if name != "config.py"
            and (references := _config_references(tree)) > CONFIG_REFERENCE_CEILINGS.get(name, 0)
        }

        assert over == {}, "a new ambient read: hand the module the value as a parameter from where it is already read, rather than raising its ceiling. A ceiling only comes down, in the commit that takes a module's reads out"

    def test_every_ceiling_names_a_module_that_is_still_there(self):
        assert sorted(set(CONFIG_REFERENCE_CEILINGS) - set(_trees())) == [], "a ceiling for a module the tree no longer has: take it out with the module"

    def test_config_is_reached_only_as_the_module(self):
        offenders = sorted(
            f"{name}:{line}"
            for name, tree in _trees().items()
            for line in _config_imports(tree)
        )

        assert offenders == [], "`import config` and `config.X`, so the ledger can see the read"

    def test_no_signature_default_is_read_off_config(self):
        offenders = sorted(
            f"{name}:{line}"
            for name, tree in _trees().items()
            for line in _import_time_config_defaults(tree)
        )

        assert offenders == [], "a default is evaluated at import and freezes the value past override_config; resolve it in the body instead"

    def test_the_overlay_keys_are_the_ones_the_contract_names(self):
        found: set[str] = set()
        unreadable: list[str] = []
        for name, tree in _trees().items():
            visitor = _OverlayKeys(
                {"_CONTENT": "", "content": ""} if name == "config.py" else None
            )
            visitor.visit(tree)
            found |= visitor.keys
            unreadable += [f"{name}:{line}" for line in visitor.unreadable]

        assert sorted(unreadable) == [], "an overlay key spelled as anything but a literal is a key this gate cannot record; spell it out"
        assert found == OVERLAY_KEYS

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
                    assert part in value
                    value = value[part]


if __name__ == "__main__":
    unittest.main()
