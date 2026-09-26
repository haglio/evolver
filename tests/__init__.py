"""Test package marker, the overlay pin, and the modal-dialog gag.

The suite runs against the committed example overlay, never the developer's
git-ignored content.local.json, so a run here matches a public checkout. This
must happen before any test module imports the app, which loads content at
import time.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import content_overlay

content_overlay.LOCAL_CONTENT = content_overlay.EXAMPLE_CONTENT

import config  # noqa: E402
from util import crash_log  # noqa: E402

# The suite's own copies of files the app keeps outside the test's reach, for
# the life of the run.
_run_state = tempfile.TemporaryDirectory(prefix="evolver-tests-", ignore_cleanup_errors=True)
RUN_STATE = Path(_run_state.name)

# No test may open a real modal dialog. Both of these block until a human clicks,
# so one unguarded call hangs an unattended suite forever instead of failing it.
# Tests that assert on an alert patch it themselves; this defuses the ones that
# reach it by accident. Never stopped -- it is an invariant, not a fixture.
# Gagged at the two calls util/alert.py makes rather than inside them: this line
# runs before any test module is read, and both are importable on an interpreter
# with no Windows, so the gag never becomes the thing that decides whether the
# suite collects at all.
patch("shared_ui.alert.show_alert", return_value=False).start()
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

# Nor the low-disk warning's dismissal, which lives beside it: every upscale run
# that finds room on its drive clears it, so a suite run would bring back a
# warning the user dismissed.
patch.object(config, "LOW_DISK_WARNING_DISMISSED_FILE",
             RUN_STATE / "low_disk_warning_dismissed").start()

# Nor the crash log, which sits in the checkout: every test that has Evolver
# step aside writes a line to it, and a suite run in the primary checkout
# would put those lines among the user's real ones.
patch.object(crash_log, "CRASH_LOG", RUN_STATE / "tray_crash.log").start()
