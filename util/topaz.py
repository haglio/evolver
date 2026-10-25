"""How both upscale stages run Topaz: the settings, the ffmpeg invocation that carries them, and whether Topaz's sign-in has expired."""

from __future__ import annotations

import logging
import os
import re
import string
import subprocess
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

import config
from util import orientation

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    """One way of running Topaz over a video, under the name and version every
    output made with it records (:mod:`util.provenance`)."""

    name: str
    version: str
    filter_complex: str
    videoai_tag: str
    keep_audio: bool = False
    # The long and short edge of the frame the settings aim at, where it aims at one
    # rather than at a scale. Its filter names them {width} and {height}, which
    # only the video's orientation settles: see framed().
    frame: tuple[int, int] | None = None


# A change to anything a set of settings runs with owes it a new version: that is how a
# later sweep tells what it made before the change from what it made after, and
# tests/test_topaz.py holds each version to the settings it shipped with.
AI_UPSCALE = Settings(
    name="ai_upscale",
    version="v002",
    filter_complex=(
        "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=1:instances=1,"
        "tvai_up=model=gcg-5:scale=4:device=0:vram=1:instances=1"
    ),
    videoai_tag=("Processed using apo-8 for 60 fps interpolation and gcg-5 for 4x upscale, "
                 "keeping the soundtrack"),
    keep_audio=True,
)
AI_UPSCALE_T2V = Settings(
    name="ai_upscale_t2v",
    version="v002",
    filter_complex=(
        "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=1:instances=1,"
        "tvai_up=model=prob-4:scale=4:preblur=0:noise=0.33:details=0.33:"
        "halo=0:blur=0.67:compression=0:estimate=20:device=0:vram=1:instances=1"
    ),
    videoai_tag=("Processed using apo-8 for 60 fps interpolation and prob-4 for 4x upscale, "
                 "keeping the soundtrack (t2v provider)"),
    keep_audio=True,
)
# What the non-AI clips processed by hand in the Topaz GUI carry in their videoai
# tags: apo-8 60 fps interpolation, then an iris-2 upscale in auto mode with
# recover-original-detail at 100 (blend=1), aimed at a 4K frame, keeping the
# soundtrack. vram=0.5 and instances=0 where the AI settings have 1 and 1: an
# unattended multi-hour encode shares the machine with whatever else is running,
# so it gets half the VRAM budget and no extra model instance -- slower, but far
# harder to push the machine into memory exhaustion.
NON_AI_UPSCALE = Settings(
    name="non_ai_upscale",
    version="v001",
    filter_complex=(
        "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=0.5:instances=0,"
        "tvai_up=model=iris-2:scale=0:w={width}:h={height}:preblur=0:noise=0:details=0:"
        "halo=0:blur=0:compression=0:estimate=20:blend=1:device=0:vram=0.5:instances=0"
    ),
    videoai_tag=("Processed using apo-8 for 60 fps interpolation and iris-2 in auto mode "
                 "with recover original detail at 100 for upscale toward 4K"),
    keep_audio=True,
    frame=(3840, 2160),
)

# download=0: Topaz otherwise stops to fetch model files it does not need, which
# on a slow connection has outlasted the stage's run budget.
AI_UPSCALE_ORIGENERATOR = Settings(
    name="ai_upscale_origenerator",
    version="v001",
    filter_complex=(
        "select='not(mod(n,{every}))',fps={kept_fps},"
        "tvai_up=model=rxl-1:scale=4:estimate=20:preblur=-0.4:noise=0:details=0.7:halo=0:"
        "blur=0.8:compression=0.8:blend=0:download=0:device=0:vram=1:instances=1,"
        "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:download=0:device=0:vram=1:instances=1"
    ),
    videoai_tag=("Processed using rxl-1 for 4x upscale of the generated frames and apo-8 "
                 "for 60 fps interpolation, keeping the soundtrack"),
    keep_audio=True,
)

ALL_SETTINGS = (AI_UPSCALE, AI_UPSCALE_T2V, NON_AI_UPSCALE, AI_UPSCALE_ORIGENERATOR)

RETIRED_SETTINGS = (
    replace(AI_UPSCALE, version="v001", keep_audio=False,
            videoai_tag="Processed using apo-8 for 60 fps interpolation and gcg-5 for 4x upscale"),
    replace(AI_UPSCALE_T2V, version="v001", keep_audio=False,
            videoai_tag=("Processed using apo-8 for 60 fps interpolation and prob-4 for 4x "
                         "upscale (t2v provider)")),
)

# A name in parentheses closing a note: the one part of the settings' note that has
# been reworded while the settings stayed the same.
_CLOSING_PARENTHETICAL = re.compile(r"\s*\([^()]*\)\s*$")

SIGN_IN_EXPIRED = "topaz_sign_in_expired"

# What Topaz's own program prints, at its verbose log level only, when the
# sign-in the Topaz Video app saved for it has run out -- and, when renewing it
# fails, that it is about to watermark everything it makes.
_EXPIRED_SIGN_IN_MESSAGES = (
    "Authentication token expired",
    "Authentication Failure",
    "Watermark will be enabled",
)
_SIGN_IN_CHECK_TIMEOUT_SECONDS = 90


def settings_noted(note: str) -> Settings | None:
    """The settings whose note Topaz wrote into a file is *note*, or None."""
    said = _CLOSING_PARENTHETICAL.sub("", note)
    return next((settings for settings in (*ALL_SETTINGS, *RETIRED_SETTINGS)
                 if _CLOSING_PARENTHETICAL.sub("", settings.videoai_tag) == said), None)


def framed(settings: Settings, orient: str, video_fps: Fraction | None = None,
           generated_fps: Fraction | None = None) -> Settings:
    """*settings* turned to the video they run over: {width} and {height} wide for
    landscape and tall otherwise, and {every} and {kept_fps} picking out the frames
    a model generating at *generated_fps* made."""
    every = _generated_frame_spacing(video_fps, generated_fps)
    settled = {"every": every, "kept_fps": video_fps / every if video_fps else "source_fps"}
    if settings.frame is not None:
        long_edge, short_edge = settings.frame
        settled["width"], settled["height"] = ((long_edge, short_edge)
                                               if orient == orientation.LANDSCAPE
                                               else (short_edge, long_edge))
    return replace(settings, filter_complex=settings.filter_complex.format(**settled))


def _generated_frame_spacing(video_fps: Fraction | None, generated_fps: Fraction | None) -> int:
    """A video written at a whole multiple of the rate its model generated at holds
    the generated frames that many apart; any other is kept whole."""
    multiple = video_fps / generated_fps if video_fps and generated_fps else Fraction(1)
    return multiple.numerator if multiple.denominator == 1 else 1


def environment() -> dict:
    """os.environ extended with the Topaz model-directory variables."""
    return {
        **os.environ,
        "TVAI_MODEL_DIR": str(config.TVAI_MODEL_DIR),
        "TVAI_MODEL_DATA_DIR": str(config.TVAI_MODEL_DIR),
    }


def command(in_file: Path, out_file: Path, settings: Settings) -> list[str]:
    """The full Topaz ffmpeg argv for one video."""
    left = [name for _, name, _, _ in string.Formatter().parse(settings.filter_complex) if name]
    if left:
        raise ValueError(f"{settings.name} still names {', '.join(left)}: "
                         "turn it to the video with framed()")
    audio_args = ["-c:a", "aac", "-b:a", "192k"] if settings.keep_audio else ["-an"]
    return [
        _ffmpeg(),
        "-hide_banner", "-nostdin", "-y",
        "-strict", "2",
        "-hwaccel", "cuda",
        "-i", str(in_file),
        "-sws_flags", "spline+accurate_rnd+full_chroma_int",
        "-filter_complex", settings.filter_complex,
        "-c:v", "hevc_nvenc",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-b_ref_mode", "disabled",
        "-tag:v", "hvc1",
        "-g", "30",
        "-preset", "p7",
        "-tune", "hq",
        "-rc", "constqp",
        "-qp", "17",
        "-rc-lookahead", "20",
        "-spatial_aq", "1",
        "-aq-strength", "15",
        "-b:v", "0",
        *audio_args,
        "-map_metadata", "0",
        "-map_metadata:s:v", "0:s:v",
        "-fps_mode:v", "cfr",
        "-movflags", "frag_keyframe+empty_moov+delay_moov+use_metadata_tags+write_colr",
        "-bf", "0",
        "-metadata", f"videoai={settings.videoai_tag}",
        "-f", "mp4",
        str(out_file),
    ]


def sign_in_expired() -> bool:
    try:
        check = subprocess.run(_sign_in_check_command(), env=environment(), capture_output=True,
                               text=True, errors="replace", check=False,
                               timeout=_SIGN_IN_CHECK_TIMEOUT_SECONDS,
                               **hidden_subprocess_kwargs())
    except (OSError, subprocess.TimeoutExpired):
        log.warning("Could not ask Topaz whether its sign-in has expired.", exc_info=True)
        return False
    return any(message in check.stderr for message in _EXPIRED_SIGN_IN_MESSAGES)


# A real encode at the verbose log level crashes Topaz's ffmpeg a few seconds
# in, after it has printed the sign-in lines, so the check is a clip of its own.
def _sign_in_check_command() -> list[str]:
    return [
        _ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "verbose",
        "-f", "lavfi", "-i", "color=c=gray:s=576x384:r=30:d=0.2",
        "-vf", "tvai_up=model=iris-2:scale=2:device=0:vram=0.5:instances=0",
        "-f", "null", "-",
    ]


def _ffmpeg() -> str:
    return str(config.FFMPEG)
