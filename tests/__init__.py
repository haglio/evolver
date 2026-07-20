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
patch(
    "util.windows_alert.ctypes.windll.user32.MessageBoxW", create=True, return_value=1,
).start()
