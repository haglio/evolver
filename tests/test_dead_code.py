"""This repo's dead-code gate. Every check it runs is `app_support.dead_code` or
`app_support.unread`, the family's one shape."""
from __future__ import annotations

from pathlib import Path

from app_support import unread
from app_support.dead_code import (
    assert_every_package_is_scanned,
    assert_no_dead_code,
    assert_no_function_takes_an_argument_it_never_reads,
    assert_nothing_is_imported_or_assigned_and_left_unread,
    assert_whitelist_is_live,
)

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = (ROOT / "backfill", ROOT / "gui", ROOT / "tasks", ROOT / "util",)
SCANNED = (*PACKAGES, ROOT / "backfill_app.py", ROOT / "check_correspondence.py", ROOT / "check_duplicate_sizes.py", ROOT / "config.py", ROOT / "content_overlay.py", ROOT / "evolver.py", ROOT / "tray_app.py", ROOT / "tools")
WHITELIST = ROOT / "vulture_whitelist.py"


def test_no_dead_code():
    assert_no_dead_code(*SCANNED, whitelist=WHITELIST)


def test_the_whitelist_still_suppresses_what_it_claims_to():
    assert_whitelist_is_live(*SCANNED, whitelist=WHITELIST)


def test_every_package_in_the_tree_is_scanned():
    assert_every_package_is_scanned(ROOT, ("backfill", "gui", "tasks", "util",))


def test_nothing_is_imported_or_assigned_and_left_unread():
    assert_nothing_is_imported_or_assigned_and_left_unread(ROOT, *SCANNED, ROOT / "tests")


def test_no_function_takes_an_argument_it_never_reads():
    assert_no_function_takes_an_argument_it_never_reads(ROOT, *SCANNED)


def test_no_module_level_constant_goes_unread():
    unread.assert_no_module_constant_goes_unread(ROOT, SCANNED)


def test_no_constructor_parameter_is_stored_and_never_read():
    unread.assert_no_constructor_parameter_is_stored_and_never_read(ROOT, SCANNED)


def test_no_dataclass_field_goes_unread():
    # finished_at is a key of the run records on disk, written by asdict and never read back:
    # retiring a persisted key is item 56's, not a deletion here.
    unread.assert_no_dataclass_field_goes_unread(ROOT, SCANNED, allowing=("RunRecord.finished_at",))


def test_every_declared_command_line_option_is_read():
    unread.assert_every_argparse_option_is_read(ROOT, SCANNED)


def test_no_test_helper_is_written_and_never_called():
    unread.assert_no_test_helper_is_written_and_never_called(ROOT, ROOT / "tests")
