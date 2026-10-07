"""The Start-with-Windows shortcut: the one Evolver's list keeps in the Startup folder.

Always the checkout the user runs, never a worktree: a preview's settings dialog
would otherwise leave Windows starting a branch at every sign-in.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from app_support import win32, windows_settings

import config

_NAME = "Evolver"
_PLACE = "startup"


def _everyday_checkout() -> Path:
    return config.LIVE_DIR


def _shortcut_path() -> Path:
    return windows_settings.shortcut_file(_everyday_checkout(), _NAME, _PLACE)


def is_registered() -> bool:
    return _shortcut_path().exists()


def register_startup() -> None:
    checkout = _everyday_checkout()
    (listed,) = [spec for spec in windows_settings.declared(checkout).shortcuts
                 if spec.name == _NAME and _PLACE in spec.places]
    shortcut = windows_settings.shortcut_for(checkout, listed)
    win32.write_shortcut(str(_shortcut_path()), **dataclasses.asdict(shortcut))


def unregister_startup() -> None:
    _shortcut_path().unlink(missing_ok=True)
