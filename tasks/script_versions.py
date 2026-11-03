from __future__ import annotations

import filecmp
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app_support.video_names import strip_processing_suffixes

from util.script_library import copy_script, script_path_for_video

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VersionCopies:
    copied: int = 0
    ambiguous_groups: int = 0
    copy_error_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AiFiling:
    source: str | None = None
    orientation: str | None = None


def ai_filing(rel: Path) -> AiFiling:
    match rel.parts[:-1]:
        case ("2D", "AI", "0_inbox", source, *_):
            return AiFiling(source)
        case ("2D", "AI", "1_sorted", source, orientation, *_):
            return AiFiling(source, orientation)
        case ("2D", "AI", "2_outbox", "upscaled_by_orientation", orientation, source, *_):
            return AiFiling(source, orientation)
    return AiFiling()


def copy_missing_version_scripts(video_index: dict[str, list[Path]], videos_root: Path,
                                 scripts_root: Path) -> VersionCopies:
    copied = 0
    ambiguous_groups = 0
    copy_error_paths: list[str] = []
    groups: dict[tuple[tuple[str, ...], str], list[Path]] = defaultdict(list)
    for matches in video_index.values():
        for video_path in matches:
            key = (version_bucket(video_path, videos_root),
                   strip_processing_suffixes(video_path.stem))
            groups[key].append(video_path)

    for (_, normalized_stem), videos in sorted(groups.items()):
        if len(videos) <= 1:
            continue

        missing_targets = [video for video in videos if not script_path_for_video(video).exists()]
        if not missing_targets:
            continue

        existing_sources = [video for video in videos if script_path_for_video(video).exists()]
        if not existing_sources:
            continue

        for target_video in sorted(missing_targets):
            source_video = _pick_version_source(target_video, existing_sources, videos_root)
            if source_video is None:
                log.warning(
                    "AMBIGUOUS VERSION SCRIPT GROUP for stem %s: %s",
                    normalized_stem,
                    ", ".join(str(script_path_for_video(video)) for video in sorted(existing_sources)),
                )
                ambiguous_groups += 1
                continue

            source_script = script_path_for_video(source_video)
            dest_script = script_path_for_video(target_video)
            try:
                copy_script(source_script, dest_script)
            except OSError:
                copy_error_paths.append(str(source_script.relative_to(scripts_root)))
                log.exception("FAILED TO COPY VERSION SCRIPT  %s  ->  %s", source_script, dest_script)
                continue
            copied += 1
            existing_sources.append(target_video)
            log.info("COPY VERSION SCRIPT  %s  ->  %s", source_script, dest_script)

    return VersionCopies(copied, ambiguous_groups, copy_error_paths)


def _pick_version_source(target_video: Path, existing_sources: list[Path],
                         videos_root: Path) -> Path | None:
    ordered = sorted(
        existing_sources,
        key=lambda path: (
            _version_kind(path, videos_root) == _version_kind(target_video, videos_root),
            str(path),
        ),
    )
    if len(ordered) == 1:
        return ordered[0]

    first_script = script_path_for_video(ordered[0])
    for candidate in ordered[1:]:
        if not filecmp.cmp(first_script, script_path_for_video(candidate), shallow=False):
            return None
    return ordered[0]


def version_bucket(video_path: Path, videos_root: Path) -> tuple[str, ...]:
    rel = video_path.relative_to(videos_root)
    filing = ai_filing(rel)
    if filing.source and filing.orientation:
        return ("2D", "AI", filing.source, filing.orientation)
    match rel.parts:
        case ("2D", "non_AI", source, *_):
            return ("2D", "non_AI", source)
    return rel.parts[:2]


def _version_kind(video_path: Path, videos_root: Path) -> str:
    rel = video_path.relative_to(videos_root)
    match rel.parts:
        case ("2D", "AI", "1_sorted", *_):
            return "original"
        case ("2D", "AI", "2_outbox", *_):
            return "processed"
    return "processed" if "processed" in rel.parts else "original"
