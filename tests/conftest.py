from __future__ import annotations

from pathlib import Path

import pytest

import config
import gui.app
from tasks import origenerator_commands
from tests import gui_support  # noqa: F401  -- builds the shared QApplication
from util import origenerator_gallery


@pytest.fixture(autouse=True)
def _a_restart_never_starts_a_real_evolver(monkeypatch):
    monkeypatch.setattr(gui.app.production_update, "start_again_after", lambda pid, launcher: None)


def _his_gallery_is_never_handed_a_test_s_records(*args, **options):
    raise AssertionError(f"a test reached Origenerator's real gallery: {args}")


@pytest.fixture(autouse=True)
def _a_test_hands_nothing_to_the_real_gallery(monkeypatch):
    monkeypatch.setattr(origenerator_commands, "_run_unseen",
                        _his_gallery_is_never_handed_a_test_s_records)



_HIS_GALLERY = Path(config.ORIGENERATOR_DB_PATH).resolve()
_read_the_gallery = origenerator_gallery.rows


def _anything_but_his_gallery(columns, *, optional=(), db_path=None):
    if Path(config.ORIGENERATOR_DB_PATH if db_path is None else db_path).resolve() == _HIS_GALLERY:
        raise AssertionError("a test reached Origenerator's real gallery; give it one of its own")
    return _read_the_gallery(columns, optional=optional, db_path=db_path)


@pytest.fixture(autouse=True)
def _records_are_staged_in_the_test_s_own_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SCRAPED_RECORDS_FILE", tmp_path / "scraped_records.json")


@pytest.fixture(autouse=True)
def _a_test_reads_no_real_gallery(monkeypatch):
    monkeypatch.setattr(origenerator_gallery, "rows", _anything_but_his_gallery)
