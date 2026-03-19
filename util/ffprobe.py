import subprocess
from pathlib import Path


def get_orientation(file: Path) -> str:
    """Return 'landscape', 'portrait', or 'unknown' based on the first video stream."""
    w_str = _probe(file, "stream=width")
    h_str = _probe(file, "stream=height")

    if not w_str or not h_str:
        return "unknown"

    try:
        w, h = int(w_str), int(h_str)
    except ValueError:
        return "unknown"

    rot_str = _probe(file, "stream_tags=rotate")
    try:
        rot = int(rot_str)
        if (rot % 180) != 0:
            w, h = h, w
    except (ValueError, TypeError):
        pass

    if w > h:
        return "landscape"
    elif h > w:
        return "portrait"
    return "landscape"  # square


def _probe(file: Path, show_entries: str) -> str:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", show_entries,
            "-of", "csv=p=0",
            str(file),
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
