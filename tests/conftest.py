"""What the whole suite runs under.

There was no conftest here at all, which is why twelve test modules each opened
by standing a QApplication up themselves. Importing `gui_support` builds the one
they now share, and does it before the first test module is imported.
"""
from __future__ import annotations

from tests import gui_support  # noqa: F401  -- builds the shared QApplication
