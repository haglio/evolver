"""The Topaz Video AI ffmpeg invocation shared by both upscale stages.

One encode recipe, two callers: the AI stage strips audio (generated clips
have none worth keeping), the non-AI stage keeps the original soundtrack.
"""

from __future__ import annotations

import os
from pathlib import Path

import config


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
