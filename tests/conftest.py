"""What the whole suite runs under.

There was no conftest here at all, which is why twelve test modules each opened
by standing a QApplication up themselves. Importing `gui_support` builds the one
they now share, and does it before the first test module is imported.
"""
from __future__ import annotations

import os
import random

import pytest

from tests import gui_support  # noqa: F401  -- builds the shared QApplication


def pytest_collection_modifyitems(items):
    """Collect in a different order when asked, so a test that leans on the ones
    beside it fails on the commit that introduces the lean.

    ``TEST_COLLECTION_ORDER=reverse`` collects back to front;
    ``TEST_COLLECTION_ORDER=shuffle`` shuffles with ``TEST_COLLECTION_SEED`` (0
    unless given), so a red run can be repeated exactly.  Unset leaves the order
    alone; anything else is a typo, and a typo that silently ran forward would
    make the gate's second leg a green that proves nothing.
    """
    order = os.environ.get("TEST_COLLECTION_ORDER")
    if order is None:
        return
    if order == "reverse":
        items.reverse()
    elif order == "shuffle":
        random.Random(int(os.environ.get("TEST_COLLECTION_SEED", "0"))).shuffle(items)
    else:
        raise pytest.UsageError(
            f"TEST_COLLECTION_ORDER={order!r}: expected 'reverse' or 'shuffle'"
        )
