"""Test package marker, the overlay pin, and the modal-dialog gag.

The suite runs against the committed example overlay, never the developer's
git-ignored content.local.json, so a run here matches a public checkout. This
must happen before any test module imports the app, which loads content at
import time.
"""
from unittest.mock import patch

import content

content.LOCAL_CONTENT = content.EXAMPLE_CONTENT

# No test may open a real modal dialog. Both of these block until a human clicks,
# so one unguarded call hangs an unattended suite forever instead of failing it.
# Tests that assert on an alert patch it themselves; this defuses the ones that
# reach it by accident. Never stopped -- it is an invariant, not a fixture.
# Gagged at the two calls util/alert.py makes rather than inside them: this line
# runs before any test module is read, and both are importable on an interpreter
# with no Windows, so the gag never becomes the thing that decides whether the
# suite collects at all.
patch("shared_ui.alert.show_alert").start()
patch("app_support.win32.show_error_popup").start()

# No test may write or delete the stand-down marker. It lives under LOCALAPPDATA,
# outside every checkout, and it is the file that tells the broker whether the
# Evolver the user is running was closed on purpose -- so a suite run that
# cleared one would put their app back up half an hour after they closed it.
# Tests that assert on these patch them again themselves, which nests fine.
# Never stopped -- an invariant, not a fixture.
#
# gui.peer_watch's other half, launching the broker, needs no gag: it starts a
# launcher found through the overlay pinned above, and the example overlay's
# project root does not exist. A test that wants it stubbed patches it.
patch("gui.peer_watch.stand_evolver_down").start()
patch("gui.peer_watch.clear_evolver_stand_down").start()
