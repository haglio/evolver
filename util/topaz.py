"""How both upscale stages run Topaz: the recipes, and the ffmpeg invocation that carries one.

The AI stage strips audio (generated clips have none worth keeping), the non-AI
stage keeps the original soundtrack.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import config


@dataclass(frozen=True)
class Recipe:
    """One way of running Topaz over a video, under the name and version every
    output made with it records (:mod:`util.provenance`)."""

    name: str
    version: str
    filter_complex: str
    videoai_tag: str


# A change to anything a recipe runs with owes it a new version: that is how a
# later sweep tells what it made before the change from what it made after, and
# tests/test_topaz.py holds each version to the settings it shipped with.
AI_UPSCALE = Recipe(
    name="ai_upscale",
    version="v001",
    filter_complex=(
        "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=1:instances=1,"
        "tvai_up=model=gcg-5:scale=4:device=0:vram=1:instances=1"
    ),
    videoai_tag="Processed using apo-8 for 60 fps interpolation and gcg-5 for 4x upscale",
)
AI_UPSCALE_T2V = Recipe(
    name="ai_upscale_t2v",
    version="v001",
    filter_complex=(
        "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=1:instances=1,"
        "tvai_up=model=prob-4:scale=4:preblur=0:noise=0.33:details=0.33:"
        "halo=0:blur=0.67:compression=0:estimate=20:device=0:vram=1:instances=1"
    ),
    videoai_tag=("Processed using apo-8 for 60 fps interpolation and prob-4 for 4x upscale "
                 "(t2v provider)"),
)


def environment() -> dict:
    """os.environ extended with the Topaz model-directory variables."""
    return {
        **os.environ,
        "TVAI_MODEL_DIR": str(config.TVAI_MODEL_DIR),
        "TVAI_MODEL_DATA_DIR": str(config.TVAI_MODEL_DIR),
    }


def command(in_file: Path, out_file: Path, filter_complex: str, videoai_tag: str,
            keep_audio: bool = False) -> list[str]:
    """The full Topaz ffmpeg argv for one video."""
    audio_args = ["-c:a", "aac", "-b:a", "192k"] if keep_audio else ["-an"]
    return [
        str(config.FFMPEG),
        "-hide_banner", "-nostdin", "-y",
        "-strict", "2",
        "-hwaccel", "cuda",
        "-i", str(in_file),
        "-sws_flags", "spline+accurate_rnd+full_chroma_int",
        "-filter_complex", filter_complex,
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
        "-metadata", f"videoai={videoai_tag}",
        "-f", "mp4",
        str(out_file),
    ]
