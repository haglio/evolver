from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from util import lanes
from util.ffprobe import has_sound
from util.library_moves import move_its_records
from util.media_files import retry_while_in_use
from util.sound import save_as_mp3

log = logging.getLogger(__name__)


def save_its_sound(flick: Path) -> None:
    if not has_sound(flick):
        return
    try:
        save_as_mp3(flick, lanes.genau_sound_of(flick))
    except (OSError, subprocess.CalledProcessError):
        log.warning("Could not save the audio of %s", flick.name, exc_info=True)


def take_the_place_of(original: Path, upscale: Path) -> bool:
    try:
        dated = original.stat().st_mtime
        retry_while_in_use(original.unlink)
    except FileNotFoundError:
        return True
    except OSError:
        log.warning("Could not retire %s; leaving it for the next run", original.name, exc_info=True)
        return False
    os.utime(upscale, (time.time(), dated))
    move_its_records(original, upscale)
    _carry_its_sound(original, upscale)
    log.info("ENHANCED IN PLACE %s", upscale)
    return True


def _carry_its_sound(original: Path, upscale: Path) -> None:
    sound = lanes.genau_sound_of(original)
    if sound.is_file():
        sound.replace(lanes.genau_sound_of(upscale))
    else:
        save_its_sound(upscale)
