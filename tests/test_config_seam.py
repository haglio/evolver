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

# What each module reads off the ambient ``config`` singleton today, held
# exactly. Lower a number when a conversion removes reads. A number goes UP only
# for a read that nothing could reach becoming an ordinary one — a value a
# module bound at its own import is not counted here and cannot be redirected
# either, so moving it into ``config`` costs references and buys the seam; say
# which in the commit. Anything else that raises a number is a new ambient read,
# and the build stops it.
#
# Per module rather than per unit, because a total lets a read added in one file
# pay for a read removed in another: a stage "converted" by hardcoding the value
# it used to look up scores exactly as well as one given a parameter. The count
# comes from the syntax tree, so a mention in a comment or a docstring does not
# move it.
#
# util/media_files.py's 1 is the other shape a number may go up for: one read
# of VIDEO_EXTENSIONS in the module that owns "what is a video", replacing
# eleven that were threaded through call sites and five identical one-line
# wrappers to say the same thing.
#
# gui/app.py's 7th and evolver.py's 10th are the third shape: a value a NEW
# feature needs that no module read before. LOG_FILE, read once on each side
# of the run-log link -- the pipeline marks where in the log it wrote, the
# window reads back what it marked -- and handed on as a parameter from
# there, so util/run_log.py and gui/log_window.py read config not at all. A
# feature paying one read where the wiring already lives is the seam working;
# paying it in the modules that do the work would not be.
CONFIG_REFERENCE_LEDGER = {
    "backfill/decisions.py": 3,
    "backfill/mic.py": 1,
    "backfill/queue.py": 1,
    "backfill/thumbnails.py": 3,
    "backfill/voice.py": 5,
    "check_correspondence.py": 6,
    "check_duplicate_sizes.py": 4,
    "evolver.py": 10,
    "gui/app.py": 7,
    "gui/main_window.py": 2,
    # The broker's launcher, so a check that finds the broker gone has something
    # to start. Where the sibling checkout is is config's business, not this
    # module's.
    "gui/peer_watch.py": 1,
    "gui/presence_throttle.py": 1,
    "gui/process_identity.py": 2,
    "gui/settings.py": 2,
    "gui/tray.py": 1,
    "gui/worker.py": 1,
    "tasks/bookmarks_sync.py": 4,
    "tasks/clip_scripts.py": 1,
    "tasks/genau_deliver.py": 5,
    "tasks/nonai_encode.py": 12,
    "tasks/nonai_group.py": 4,
    "tasks/nonai_progress.py": 1,
    "tasks/nonai_queue.py": 3,
    "tasks/nonai_upscale.py": 27,
    "tasks/origenerator_metadata.py": 1,
    "tasks/prompt_scrape.py": 5,
    "tasks/purge_weird.py": 5,
    "tasks/scene_scripts.py": 1,
    "tasks/scripts_sync.py": 19,
    "tasks/sort.py": 2,
    "tasks/stray_files.py": 8,
    "tasks/upscale.py": 17,
    "tasks/video_types.py": 14,
    "util/funscript.py": 3,
    "util/media_files.py": 1,
    "util/nonai_library.py": 5,
    "util/nonai_retire.py": 3,
    "util/reference_stores.py": 6,
    "util/sidecar.py": 4,
    "util/topaz.py": 3,
    "util/video_locator.py": 3,
}

# Every key the app reads out of the content overlay, as ``key`` or
# ``key.subkey``. ``genau_source`` is origenerator's too.
OVERLAY_KEYS = {
    "acts",
    "chrome_profile",
    "curated_examples",
    "excerpt_folders",
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
        for name in _source_files(PROJECT_ROOT)
    }


class TestConfigSeam(unittest.TestCase):
    def test_the_config_reference_count_matches_the_ledger(self):
        counts = {
            name: references
            for name, tree in _trees().items()
            if name != "config.py" and (references := _config_references(tree))
        }

        self.assertEqual(
            counts,
            CONFIG_REFERENCE_LEDGER,
            "lower a module's number in the commit that removes its reads; a "
            "number going up is a new ambient read unless the commit says why",
        )

    def test_config_is_reached_only_as_the_module(self):
        offenders = sorted(
            f"{name}:{line}"
            for name, tree in _trees().items()
            for line in _config_imports(tree)
        )

        self.assertEqual(
            offenders,
            [],
            "`import config` and `config.X`, so the ledger can see the read",
        )

    def test_no_signature_default_is_read_off_config(self):
        offenders = sorted(
            f"{name}:{line}"
            for name, tree in _trees().items()
            for line in _import_time_config_defaults(tree)
        )

        self.assertEqual(
            offenders,
            [],
            "a default is evaluated at import and freezes the value past "
            "override_config; resolve it in the body instead",
        )

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
