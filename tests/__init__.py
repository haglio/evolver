"""Test package marker, the overlay pin, and the modal-dialog gag.

The suite runs against the committed example overlay and the example of the
settings all of Haglio shares, never the developer's git-ignored
content.local.json or ~/.haglio, so a run here matches a public checkout. This
must happen before any test module imports the app, which loads content at
import time.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from app_support import haglio_settings
from app_support.testing import error_popup
from shared_ui.testing import alert_shown

import content_overlay

os.environ[haglio_settings.SETTINGS_ENV] = haglio_settings.THE_EXAMPLE
content_overlay.LOCAL_CONTENT = content_overlay.EXAMPLE_CONTENT

import config  # noqa: E402
from util import crash_log  # noqa: E402

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
alert_shown(return_value=False).start()
error_popup().start()

patch("gui.peer_watch.stand_evolver_down").start()
patch("gui.peer_watch.clear_evolver_stand_down").start()

patch.object(config, "LOW_DISK_WARNING_DISMISSED_FILE",
             RUN_STATE / "low_disk_warning_dismissed").start()

patch.object(crash_log, "CRASH_LOG", RUN_STATE / "tray_crash.log").start()
