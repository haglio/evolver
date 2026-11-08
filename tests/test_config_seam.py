from __future__ import annotations

import ast
import json
import unittest
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.product_sources import PROJECT_ROOT, product_sources

pytestmark = pytest.mark.repo_check

CONFIG_REFERENCE_CEILINGS = {
    "check_correspondence.py": 6,
    "check_duplicate_sizes.py": 4,
    "evolver.py": 11,
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
    "review_trash/window.py": 1,
    "tasks/bookmarks_sync.py": 4,
    "tasks/clip_scripts.py": 1,
    "tasks/genau_deliver.py": 5,
    "tasks/nonai_encode.py": 9,
    "tasks/nonai_files.py": 7,
    "tasks/nonai_group.py": 1,
    "tasks/nonai_queue.py": 2,
    "tasks/nonai_upscale.py": 1,
    "tasks/origenerator_commands.py": 1,
    "tasks/prompt_scrape.py": 6,
    "tasks/provenance_sweep.py": 1,
    "tasks/reference_sync.py": 2,
    "tasks/scene_scripts.py": 1,
    "tasks/scripts_sync.py": 8,
    "tasks/sort.py": 3,
    "tasks/stray_files.py": 9,
    "tasks/upscale.py": 11,
    "tasks/video_kinds.py": 6,
    "tasks/watch_weights.py": 4,
    "tasks/unsent_videos.py": 7,
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
    "util/trash_folders.py": 9,
}

OVERLAY_KEYS = {
    "cameras",
    "chrome_profile",
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

OPTIONAL_OVERLAY_KEYS = {
    "display_timezone", "retired_root", "topaz_ffmpeg",
    "topaz_models", "version_overrides", "vr_videos", "warm_gun_outbox",
}


def _loads_of_the_name_config_however_spelled(tree: ast.AST) -> int:
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "config" and isinstance(node.ctx, ast.Load)
    )


def _config_imports(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "config":
            lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            lines += [node.lineno for a in node.names if a.name == "config" and a.asname]
    return lines


def _import_time_config_defaults(tree: ast.AST) -> list[int]:
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
    def __init__(self, prebound: dict[str, str] | None = None):
        self.paths: dict[str, str] = dict(prebound or {})
        self.keys: set[str] = set()
        self.unreadable: list[int] = []

    def _path_of(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.paths.get(node.id)
        if isinstance(node, ast.Call):
            return self._path_of_call(node)
        if isinstance(node, ast.Subscript):
            return self._path_of_subscript(node)
        return None

    def _path_of_call(self, node: ast.Call) -> str | None:
        if not isinstance(node.func, ast.Name):
            return None
        if node.func.id == "load_content":
            return ""
        if node.func.id != "overlay_value" or not node.args:
            return None
        base = self._path_of(node.args[0])
        if base is None:
            return None
        keys = node.args[1:]
        if all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in keys):
            return ".".join([base, *(key.value for key in keys)]).lstrip(".")
        self.unreadable.append(node.lineno)
        return None

    def _path_of_subscript(self, node: ast.Subscript) -> str | None:
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
            key = node.args[0] if node.args else None
            if func.attr == "get" and isinstance(key, ast.Constant) and isinstance(key.value, str):
                self.keys.add(f"{base}.{key.value}".lstrip("."))
            else:
                self.unreadable.append(node.lineno)
        self.generic_visit(node)


_CONFIGS_OVERLAY_NAMES = {"_CONTENT": "", "content": ""}


def _overlay_keys_of(name: str, tree: ast.AST) -> _OverlayKeys:
    visitor = _OverlayKeys(_CONFIGS_OVERLAY_NAMES if name == "config.py" else None)
    visitor.visit(tree)
    return visitor


def _run_at_import(statements: list[ast.stmt]) -> Iterator[ast.AST]:
    for statement in statements:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from statement.decorator_list
        elif isinstance(statement, ast.ClassDef):
            yield from (*statement.decorator_list, *statement.bases, *statement.keywords)
            yield from _run_at_import(statement.body)
        else:
            yield statement


def _stage_bindings_read_off_config(tree: ast.Module) -> list[int]:
    return [
        inner.lineno
        for statement in _run_at_import(tree.body)
        for inner in ast.walk(statement)
        if isinstance(inner, ast.Name) and inner.id == "config" and isinstance(inner.ctx, ast.Load)
    ]


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
            and (references := _loads_of_the_name_config_however_spelled(tree)) > CONFIG_REFERENCE_CEILINGS.get(name, 0)
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

    def test_the_overlay_keys_kept_out_of_this_public_repo_are_the_ones_the_contract_names(self):
        found: set[str] = set()
        unreadable: list[str] = []
        for name, tree in _trees().items():
            visitor = _overlay_keys_of(name, tree)
            found |= visitor.keys
            unreadable += [f"{name}:{line}" for line in visitor.unreadable]

        assert sorted(unreadable) == [], "an overlay key spelled as anything but a literal is a key this gate cannot record; spell it out"
        assert found == OVERLAY_KEYS

    def test_the_committed_example_carries_every_key_a_public_checkout_imports_config_with(self):
        example = json.loads(
            Path(PROJECT_ROOT, "content.example.json").read_text(encoding="utf-8")
        )

        for key in sorted(OVERLAY_KEYS - OPTIONAL_OVERLAY_KEYS):
            with self.subTest(key=key):
                value = example
                for part in key.split("."):
                    assert part in value
                    value = value[part]

    def test_a_dict_named_content_outside_config_is_not_taken_for_the_overlay(self):
        tree = ast.parse('content = {"alpha": 1}\ncontent["alpha"]\ncontent.get("beta")\n')

        assert _overlay_keys_of("tasks/alpha.py", tree).keys == set()

    def test_an_acts_entrys_own_fields_are_not_taken_for_overlay_keys(self):
        tree = ast.parse('spoken = [act["spoken"] for act in load_content()["acts"]]\n')

        assert _overlay_keys_of("config.py", tree).keys == {"acts"}

    def test_the_example_leaves_every_optional_key_to_its_fallback_rather_than_one_computers_answer(self):
        example = json.loads(
            Path(PROJECT_ROOT, "content.example.json").read_text(encoding="utf-8")
        )

        assert sorted(OPTIONAL_OVERLAY_KEYS & set(example)) == []

    def test_no_stage_binds_a_config_value_at_its_own_import_where_override_config_cannot_reach_it(self):
        offenders = sorted(
            f"{name}:{line}"
            for name, tree in _trees().items()
            if name.startswith("tasks/")
            for line in _stage_bindings_read_off_config(tree)
        )

        assert offenders == []


if __name__ == "__main__":
    unittest.main()
