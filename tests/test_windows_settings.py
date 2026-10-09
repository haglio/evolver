"""What Evolver relies on Windows to keep, as its pyproject lists it.

``python -m app_support.windows_settings`` makes the machine match the list;
what is Evolver's own about it is held here.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from app_support.launcher import launchers

from gui.process_identity import APP_MODEL_ID

REPO_ROOT = Path(__file__).resolve().parents[1]
LISTED = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["haglio"]
RUNS = {launcher.file: launcher.run for launcher in launchers(REPO_ROOT)}


def _what_shortcuts_run_from(*places: str) -> list[str]:
    return [RUNS[spec["launcher"]] for spec in LISTED["shortcuts"].values()
            if set(spec["places"]) & set(places)]


def test_the_shortcut_windows_starts_at_sign_in_leaves_a_running_evolver_alone():
    (run,) = _what_shortcuts_run_from("startup")

    assert run.endswith(" --if-not-running")


def test_a_shortcut_clicked_to_open_evolver_opens_the_running_ones_window():
    clicked = _what_shortcuts_run_from("taskbar", "start-menu", "checkout")

    assert clicked
    assert not [run for run in clicked if "--if-not-running" in run]


def test_what_the_list_starts_is_one_of_this_checkouts_launchers():
    declared = {launcher.file for launcher in launchers(REPO_ROOT)}

    assert {spec["launcher"] for spec in LISTED["shortcuts"].values()} <= declared


def test_the_icon_each_shortcut_shows_is_in_this_checkout():
    for spec in LISTED["shortcuts"].values():
        assert (REPO_ROOT / spec["icon"]).is_file(), spec["icon"]


def test_each_shortcut_carries_the_identity_the_app_claims():
    assert {spec["app-id"] for spec in LISTED["shortcuts"].values()} == {APP_MODEL_ID}
