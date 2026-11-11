from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_suites_application_ends_cleanly_with_a_python_filter_watching_live_windows():
    child = textwrap.dedent("""
        from PySide6.QtWidgets import QTableWidget
        from shared_ui.tooltip_shape import shape_long_tooltips
        from tests.gui_support import QAPP

        shape_long_tooltips(QAPP)
        kept = [QTableWidget(3, 3) for _ in range(200)]
        for table in kept:
            table.show()
    """)
    ran = subprocess.run([sys.executable, "-c", child], cwd=REPO_ROOT, timeout=120,
                         env=os.environ | {"QT_QPA_PLATFORM": "offscreen"},
                         capture_output=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)

    assert ran.returncode == 0, ran.stdout + ran.stderr
