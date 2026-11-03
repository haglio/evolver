"""Evolver's half of the pair that keeps Evolver and the broker both up.

Evolver has never had a supervisor. It starts from a Startup-folder shortcut and
that is all, so any death — a crash, a kill from the task list, the quit it
performs on itself when Windows announces a session end that is then cancelled —
leaves it down until the next sign-in. Its own log shows what that costs: seven
outages of six hours or more in a single month, one of eight days, one of
thirteen, every one of them silent.

The broker, next door, already has one: a scheduled task that relaunches its tray
every couple of minutes, and a tray that in turn keeps the broker process alive.
Pairing the two hands Evolver that supervisor for free — the task revives the
broker's tray, and the tray revives Evolver — while Evolver covers the one thing
the task cannot, which is the task itself being switched off. Neither ever kills
anything: each only starts a peer that answered "not running", and each relies on
the other's single-instance mutex to make a launch over a live peer a no-op.

What stops this arguing with the user is :mod:`app_support.peer_watch`'s
stand-down marker. Quitting Evolver from its tray writes one and the broker
leaves it down; every other way Evolver dies leaves none and it comes back.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app_support import peer_watch
from app_support.subprocess_utils import hidden_subprocess_kwargs
from app_support.win32 import is_mutex_held

import config
from util import crash_log

# The Qt timer that drives the watch beats at the same rate the watch throttles
# to, so here a beat and a check are the same thing. The rate itself is the
# shared one: both halves of the pair look for each other equally often.
PEER_CHECK_INTERVAL_MS = int(peer_watch.DEFAULT_INTERVAL_SECONDS * 1000)

EVOLVER_KEY = "evolver"
BROKER_KEY = "broker"

BROKER_TRAY_MUTEX = "Global\\OSR2Broker.Tray"


def broker_tray_is_up(*, is_held=is_mutex_held) -> bool:
    return is_held(BROKER_TRAY_MUTEX)


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
        is_up=lambda: broker_tray_is_up(),
        launch=lambda: launch_broker_tray(),
        **kwargs,
    )


def stand_evolver_down() -> None:
    peer_watch.stand_down(EVOLVER_KEY)


def clear_evolver_stand_down() -> None:
    peer_watch.clear_stand_down(EVOLVER_KEY)
