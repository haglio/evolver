"""The launch smoke test: everything ``pythonw tray_app.py`` imports, imported.

The suite can be entirely green while the tray icon never appears, and this is
the gap. ``tray_app.py`` imports the app itself -- ``from gui.app import
EvolverApp`` -- *inside* ``main()``, after the crash-log hook is installed, so
a break anywhere under ``gui`` never touches a test that imports ``tray_app``
and stops at module level. ``tests/test_app_startup.py`` constructs
``EvolverApp`` but does it in the pytest process, where the suite's own imports
and ``tests/__init__.py``'s overlay pin have already run; the shortcut has
neither.

``pythonw`` is what makes a failure invisible rather than merely broken: it has
no console, so an import that fails before ``report_startup_crash`` can run
writes its traceback nowhere at all.

So this drives the launch's import phase the way the shortcut does: a fresh
interpreter, this repo as the working directory (which is what puts
``tray_app.py`` beside its ``gui`` and ``util`` packages), no inherited
``PYTHONPATH``, and the committed example overlay standing in for the
git-ignored local one -- which is also what a public checkout and CI have.

The statements come off the AST of the two files the launch executes rather
than a list maintained here, because a hand-written list is exactly what would
drift. They are replayed as whole ``from X import a, b`` statements, not as
``import X``, so a symbol the launch names but the module no longer defines
fails here too.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# tray_app.py is a script beside the packages, not a package of its own, so no
# relative import can appear in the launch files and there is nothing to resolve
# them against.
PACKAGE = ""

# The two files the shortcut runs: the script, and the module holding the app.
LAUNCH_FILES = (
    REPO_ROOT / "tray_app.py",
    REPO_ROOT / "gui" / "app.py",
)

# Reached only from inside main(), so a module-level import test never saw it.
# Asserted present, so a walk that silently found nothing -- a renamed file, a
# parse that returned an empty tree -- cannot pass as a clean launch.
_REACHED_ONLY_FROM_INSIDE_MAIN = ("gui.app",)

# Only these two. A broad ``except Exception`` around a launch body is an error
# *reporter* -- it puts a dialog on screen or writes a crash log -- so an import
# inside it is required, not optional: it failing is exactly the launch failure
# this file exists to catch.
_TOLERATED_BY = {"ImportError", "ModuleNotFoundError"}


# --------------------------------------------------------------------------
# What the launch imports
# --------------------------------------------------------------------------

def _is_type_checking(test: ast.expr) -> bool:
    """``if TYPE_CHECKING:`` bodies are never executed, at launch or anywhere."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _tolerates_a_missing_module(handlers: list[ast.ExceptHandler]) -> bool:
    for handler in handlers:
        if handler.type is None:  # bare except -- catches everything, promises nothing
            return False
        caught = (
            handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        )
        if any(isinstance(n, ast.Name) and n.id in _TOLERATED_BY for n in caught):
            return True
    return False


def _optional_imports(tree: ast.Module) -> set[int]:
    """Imports whose absence the module already handles, so the launch survives
    them and this test must not insist on them."""
    optional: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            body = node.body
        elif isinstance(node, ast.Try) and _tolerates_a_missing_module(node.handlers):
            body = node.body
        else:
            continue
        for statement in body:
            for inner in ast.walk(statement):
                optional.add(id(inner))
    return optional


def _render(node: ast.Import | ast.ImportFrom, package: str) -> str:
    """The import statement as the launch executes it, relative made absolute.

    Every launch file here sits at the top of its package, so a relative import
    is never deeper than one level.
    """
    names = ", ".join(
        alias.name + (f" as {alias.asname}" if alias.asname else "")
        for alias in node.names
    )
    if isinstance(node, ast.Import):
        return f"import {names}"
    assert node.level <= 1, f"unexpected relative import depth in {package}"
    module = node.module or ""
    if node.level:
        module = f"{package}.{module}" if module else package
    return f"from {module} import {names}"


def _is_a_compiler_directive(node: ast.Import | ast.ImportFrom) -> bool:
    """``from __future__ import ...`` loads no module -- it is a flag to the
    compiler, and it is only legal at the top of a file, so replaying it among
    the others is a SyntaxError rather than a check of anything."""
    return isinstance(node, ast.ImportFrom) and node.module == "__future__"


def _launch_imports(package: str, launch_files) -> list[str]:
    statements: list[str] = []
    for path in launch_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        optional = _optional_imports(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if id(node) in optional or _is_a_compiler_directive(node):
                continue
            statements.append(_render(node, package))
    return statements


def _run_the_launchs_way(statements: list[str]) -> subprocess.CompletedProcess:
    """Run them the way the shortcut runs ``tray_app.py``.

    Its own directory is what Python puts on ``sys.path`` for a script, and it
    is what makes ``gui`` and ``util`` importable, so the working directory is
    the whole path story -- any ``PYTHONPATH`` a developer or pytest happens to
    be carrying is dropped, because the shortcut does not get it.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["QT_QPA_PLATFORM"] = "offscreen"

    driver = "\n".join(
        [
            # Before anything that reads content at import time: a public
            # checkout has only the committed example, so that is what the
            # launch has to come up on.
            "import content as _content",
            "_content.LOCAL_CONTENT = _content.EXAMPLE_CONTENT",
            *statements,
        ]
    )
    return subprocess.run(
        [sys.executable, "-c", driver],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_the_launch_imports_everything_it_names():
    """Failing here means the tray icon never appears and nothing says why:
    pythonw has no console, and the failure precedes the crash-log hook."""
    result = _run_the_launchs_way(_launch_imports(PACKAGE, LAUNCH_FILES))

    assert result.returncode == 0, result.stderr


def test_the_walk_reaches_the_imports_buried_in_main():
    """The guard above is only worth anything if the walk found the lazy one --
    which is the entire app."""
    found = "\n".join(_launch_imports(PACKAGE, LAUNCH_FILES))

    for module in _REACHED_ONLY_FROM_INSIDE_MAIN:
        assert module in found, f"the launch imports {module}; the walk missed it"


def test_a_launch_import_that_cannot_resolve_fails_here():
    """A negative control: if the subprocess reported success regardless, every
    assertion above would pass vacuously and the guard would be decorative."""
    result = _run_the_launchs_way(
        [*_launch_imports(PACKAGE, LAUNCH_FILES), "from gui.app import NoSuchSymbol"]
    )

    assert result.returncode != 0
    assert "NoSuchSymbol" in result.stderr


def test_the_app_relaunches_itself_the_same_way_the_shortcut_does():
    """Restart is how the user picks up a new version, from the tray menu or the
    toolbar, so it is a launch too -- and it runs the same script this test
    covers, on the interpreter already running."""
    text = (REPO_ROOT / "gui" / "app.py").read_text(encoding="utf-8")

    assert 'config.PROJECT_DIR / "tray_app.py"' in text
    assert "sys.executable" in text
