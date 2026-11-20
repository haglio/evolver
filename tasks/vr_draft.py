from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LOOKING_DOWN_DEGREES = -29.358
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def lens_of(name: str) -> str:
    named = name.lower()
    if "mkx200" in named:
        return "crop=iw/2:ih:0:0,v360=input=fisheye:output=flat:ih_fov=200:iv_fov=200:"
    if "fisheye" in named or "rf52" in named:
        return "crop=iw/2:ih:0:0,v360=input=fisheye:output=flat:ih_fov=190:iv_fov=190:"
    if "_360" in named:
        return "v360=input=equirect:output=flat:"
    return "crop=iw/2:ih:0:0,v360=input=hequirect:output=flat:"


def flatten_command(video: Path, flat: Path) -> list[str]:
    view = (f"fps=30,format=yuv420p,{lens_of(video.name)}h_fov=90:v_fov=58.71550708558254:"
            f"w=1024:h=576:yaw=0:pitch={LOOKING_DOWN_DEGREES:.4f}:roll=0,scale=-2:576:flags=bicubic")
    return ["ffmpeg", "-y", "-v", "error", "-hwaccel", "cuda", "-i", str(video), "-an", "-vf", view,
            "-c:v", "h264_nvenc", "-rc", "constqp", "-qp", "18", str(flat)]


def main(arguments: list[str], *, run=subprocess.run) -> int:
    video, flat, _, *draft = arguments
    Path(flat).parent.mkdir(parents=True, exist_ok=True)
    flattened = run(flatten_command(Path(video), Path(flat)), creationflags=_NO_WINDOW)
    if flattened.returncode:
        return flattened.returncode
    return run(draft, creationflags=_NO_WINDOW).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
