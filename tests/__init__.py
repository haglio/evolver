"""Test package marker, the overlay pin, and the modal-dialog gag.

The suite runs against the committed example overlay, never the developer's
git-ignored content.local.json, so a run here matches a public checkout. This
must happen before any test module imports the app, which loads content at
import time.
"""
from unittest.mock import patch

import content

content.LOCAL_CONTENT = content.EXAMPLE_CONTENT

# No test may open a real modal dialog. MessageBoxW blocks until a human clicks
# it, so one unguarded call hangs an unattended suite forever instead of failing
# it. Tests that assert on an alert patch it themselves; this defuses the ones
# that reach it by accident. Never stopped — it is an invariant, not a fixture.
# Gagged at the one name in this repo that reaches MessageBoxW rather than at
# ctypes.windll.user32: this line runs before any test module is read, and the
# dotted path through ctypes.windll cannot be resolved on an interpreter that
# has no Windows — which made this gag, not the platform, the thing that decided
# whether the suite collected at all.
patch("util.windows_alert._message_box_w", return_value=1).start()
