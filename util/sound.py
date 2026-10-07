"""A video's soundtrack, saved on its own for a player that plays sound files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def save_as_mp3(video: Path, mp3: Path) -> None:
    mp3.parent.mkdir(parents=True, exist_ok=True)
    partial = mp3.with_name(f"{mp3.stem}.partial.mp3")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(video), "-vn",
         "-map", "0:a:0", "-map_metadata", "-1", "-c:a", "libmp3lame", "-q:a", "2",
         str(partial)],
        check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    os.replace(partial, mp3)
