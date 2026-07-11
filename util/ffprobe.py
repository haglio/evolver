import subprocess
from pathlib import Path


def video_dimensions(file: Path) -> tuple[int, int] | None:
    """The (width, height) of a file's first video stream, or None if unavailable.

    Raw stored dimensions — rotation is not applied. Callers that need display
    orientation (see :func:`get_orientation`) fold the rotate tag in themselves.
    """
    w_str = _probe(file, "stream=width")
    h_str = _probe(file, "stream=height")
    if not w_str or not h_str:
        return None
    try:
        return int(w_str), int(h_str)
    except ValueError:
        return None


def get_orientation(file: Path) -> str:
    """Return 'landscape', 'portrait', or 'unknown' based on the first video stream."""
    dims = video_dimensions(file)
    if dims is None:
        return "unknown"
    w, h = dims

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


def duration_seconds(file: Path) -> float | None:
    """The container duration of *file* in seconds, or None if unavailable."""
    try:
        return float(_probe_format(file, "format=duration"))
    except ValueError:
        return None


def videoai_tag(file: Path) -> str:
    """The Topaz ``videoai`` metadata tag of *file* — empty when untagged."""
    return _probe_format(file, "format_tags=videoai")


def _probe(file: Path, show_entries: str) -> str:
    return _run_ffprobe(["-select_streams", "v:0", "-show_entries", show_entries, str(file)])


def _probe_format(file: Path, show_entries: str) -> str:
    return _run_ffprobe(["-show_entries", show_entries, str(file)])


def _run_ffprobe(args: list[str]) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-of", "csv=p=0", *args],
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return result.stdout.strip()
