from __future__ import annotations

import pytest
from PyQt6.QtGui import QPalette
from shared_ui.colors import BLUE, BLUE_LIGHT, TEXT_PRIMARY

from tests.gui_support import QAPP, build_evolver_app


@pytest.fixture
def palette(request) -> QPalette:
    build_evolver_app(request)
    return QAPP.palette()


def test_a_link_wears_the_family_blue_rather_than_the_windows_accent(palette):
    assert palette.color(QPalette.ColorRole.Link).name() == BLUE.name()


def test_a_clicked_link_turns_the_lighter_blue_every_app_of_the_family_shows(palette):
    assert palette.color(QPalette.ColorRole.LinkVisited).name() == BLUE_LIGHT.name()


def test_a_selection_wears_the_family_blue_rather_than_the_windows_accent(palette):
    assert palette.color(QPalette.ColorRole.Highlight).name() == BLUE.name()


def test_selected_text_is_the_familys_brightest_not_the_black_windows_pairs_with_its_accent(palette):
    assert palette.color(QPalette.ColorRole.HighlightedText).name() == TEXT_PRIMARY.name()
