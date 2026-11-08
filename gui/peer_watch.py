
from __future__ import annotations

import subprocess
from pathlib import Path

from app_support import peer_watch
from app_support.subprocess_utils import hidden_subprocess_kwargs
from app_support.win32 import is_mutex_held

import config
from util import crash_log

PEER_CHECK_INTERVAL_MS = int(peer_watch.DEFAULT_INTERVAL_SECONDS * 1000)

EVOLVER_KEY = "evolver"
BROKER_KEY = "broker"

BROKER_TRAY_MUTEX = "Global\\OSR2Broker.Tray"


def broker_tray_is_up(*, is_held=is_mutex_held) -> bool:
    return is_held(BROKER_TRAY_MUTEX)


# The OSR2 Broker's tray holds Global\OSR2Broker.Tray and refuses a second copy of itself, so a
# launch that races a tray coming up does nothing.
def launch_broker_tray(
    *,
    launcher: Path | None = None,
    popen=subprocess.Popen,
) -> None:
    launcher = config.BROKER_TRAY_LAUNCHER if launcher is None else launcher
    if not launcher.is_file():
        return
    popen(["wscript.exe", str(launcher)], cwd=str(launcher.parent),
          **hidden_subprocess_kwargs())
    crash_log.write_info(
        "Broker was not running:", f"started it from {launcher}\n")


def watch_the_broker(**kwargs) -> peer_watch.PeerWatch:
    return peer_watch.PeerWatch(
        peer_key=BROKER_KEY,
        is_up=broker_tray_is_up,
        launch=launch_broker_tray,
        **kwargs,
    )


def stand_evolver_down() -> None:
    peer_watch.stand_down(EVOLVER_KEY)


def clear_evolver_stand_down() -> None:
    peer_watch.clear_stand_down(EVOLVER_KEY)
