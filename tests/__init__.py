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

alert_shown(return_value=False).start()
error_popup().start()

patch("gui.peer_watch.stand_evolver_down").start()
patch("gui.peer_watch.clear_evolver_stand_down").start()

patch.object(config, "LOW_DISK_WARNING_DISMISSED_FILE",
             RUN_STATE / "low_disk_warning_dismissed").start()

patch.object(crash_log, "CRASH_LOG", RUN_STATE / "tray_crash.log").start()
