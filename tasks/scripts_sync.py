from __future__ import annotations

import filecmp
import logging
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

from app_support.video_names import strip_processing_suffixes

import config
from util import lanes
from util.alert import show_error
from util.media_files import (
    library_videos,
    reachable,
    remove_empty_dirs,
    unique_path,
)
from util.script_library import (
    carry_mark,
    copy_script,
    drop_mark,
    remove_empty_mark_folders,
    script_path_for_video,
)

log = logging.getLogger(__name__)


@dataclass
class ScriptsSyncResult:
    moved: int = 0
    already_aligned: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    collisions: int = 0
    copied_variants: int = 0
    ambiguous_variant_groups: int = 0
    variant_copy_errors: int = 0
    rehomed_to_variants: int = 0
    followed_to_archive: int = 0
    discarded_duplicates: int = 0
    not_checked: int = 0
    unreachable: list[str] = field(default_factory=list)
    unmatched_paths: list[str] = field(default_factory=list)
    ambiguous_paths: list[str] = field(default_factory=list)
    collision_paths: list[str] = field(default_factory=list)
    variant_copy_error_paths: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.unmatched or self.ambiguous or self.collisions or self.variant_copy_errors)


class _Duplicate(Enum):
    DISCARDED = auto()
    COLLIDED = auto()


@dataclass(frozen=True)
class _VersionRehome:
    moved: bool = False
    archived_copy: bool = False


@dataclass(frozen=True)
class _FollowedRetired:
    unmatched: list[Path] = field(default_factory=list)
    followed_to_archive: int = 0
    rehomed_to_variants: int = 0
    collision_paths: list[str] = field(default_factory=list)
    discarded_duplicates: int = 0


@dataclass(frozen=True)
class Trees:
    videos: Path
    scripts: Path
    unmatched: Path
    archive: Path | None
    vr: Path | None

    @classmethod
    def configured(cls) -> Trees:
        return cls(
            videos=config.VIDEO_LIBRARY_DIR,
            scripts=config.SCRIPT_LIBRARY_DIR,
            unmatched=config.UNMATCHED_SCRIPTS_DIR,
            archive=config.NONAI_RETIRED_ROOT,
            vr=config.VR_VIDEO_DIR,
        )


@dataclass(frozen=True)
class _VersionCopies:
    copied: int = 0
    ambiguous_groups: int = 0
    copy_error_paths: list[str] = field(default_factory=list)


def run(show_popup: bool = False, *, trees: Trees | None = None) -> ScriptsSyncResult:
    trees = Trees.configured() if trees is None else trees
    result = ScriptsSyncResult()
    trees.scripts.mkdir(parents=True, exist_ok=True)

    log.info("=== Stage: scripts -> mirror video library ===")
    log.info("VIDEOS:  %s", trees.videos)
    log.info("SCRIPTS: %s", trees.scripts)

    vr_out_of_reach = trees.vr is not None and not reachable(trees.vr)
    if vr_out_of_reach:
        result.unreachable.append(str(trees.vr))
    video_index = _index_videos(trees)

    orphans = _align_scripts(trees, video_index, result, vr_out_of_reach)

    if orphans and trees.archive is not None and not reachable(trees.archive):
        result.unreachable.append(str(trees.archive))
        result.not_checked += len(orphans)
    else:
        followed = _follow_retired_videos(orphans, video_index, trees)
        result.unmatched_paths += [_park(script_path, trees) for script_path in followed.unmatched]
        result.followed_to_archive += followed.followed_to_archive
        result.rehomed_to_variants += followed.rehomed_to_variants
        result.collision_paths += followed.collision_paths
        result.discarded_duplicates += followed.discarded_duplicates
    _tidy_and_copy_versions(trees, video_index, result)
    _report(result, trees, show_popup)
    return result


def _tidy_and_copy_versions(trees: Trees, video_index: dict[str, list[Path]],
                            result: ScriptsSyncResult):
    remove_empty_dirs(trees.scripts)
    remove_empty_mark_folders()
    versions = _copy_missing_version_scripts(video_index, trees)
    result.copied_variants += versions.copied
    result.ambiguous_variant_groups += versions.ambiguous_groups
    result.variant_copy_error_paths += versions.copy_error_paths
    result.unmatched = len(result.unmatched_paths)
    result.ambiguous = len(result.ambiguous_paths)
    result.collisions = len(result.collision_paths)
    result.variant_copy_errors = len(result.variant_copy_error_paths)


def _report(result: ScriptsSyncResult, trees: Trees, show_popup: bool):
    _log_summary(result)
    if result.not_checked:
        log.warning("%d funscript(s) not checked: %s cannot be reached, so they stay where they "
                    "are until it can be.", result.not_checked, " and ".join(result.unreachable))
    if not result.ok:
        log.error("Scripts sync failed. See log entries above for unresolved funscript alignment issues.")
        if show_popup:
            log.info("Showing error popup for scripts-sync failure")
            links = [("Open unmatched_scripts", trees.unmatched)] if result.unmatched_paths else []
            show_error("Evolver - Funscript Match Error", _popup_message(result), links=links)
            log.info("Error popup closed")


def _align_scripts(trees: Trees, video_index: dict[str, list[Path]],
                   result: ScriptsSyncResult, vr_out_of_reach: bool) -> list[Path]:
    orphans: list[Path] = []
    for script_path in _iter_funscripts(trees.scripts, trees.unmatched):
        if vr_out_of_reach and _may_match_a_vr_video(script_path, trees):
            result.not_checked += 1
            continue
        matches = _matching_videos_for_script(script_path, video_index, trees)
        if not matches:
            orphans.append(script_path)
            continue
        if len(matches) > 1:
            log.warning("AMBIGUOUS script match for %s: %s", script_path, ", ".join(str(p) for p in matches))
            result.ambiguous_paths.append(_shown(script_path, trees))
            continue

        dest = script_path_for_video(matches[0])
        if script_path == dest:
            result.already_aligned += 1
            continue
        if dest.exists():
            log.warning("SCRIPT COLLISION (destination exists, leaving source in place): %s -> %s", script_path, dest)
            result.collision_paths.append(_shown(script_path, trees))
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        log.info("MOVE SCRIPT  %s  ->  %s", script_path, dest)
        script_path.rename(dest)
        carry_mark(script_path, dest)
        result.moved += 1
    return orphans


def _log_summary(result: ScriptsSyncResult):
    log.info(
        "Scripts sync done. Moved: %d, Already aligned: %d, Unmatched: %d, Ambiguous: %d, Collisions: %d, Version copies: %d, Ambiguous version groups: %d, Version copy errors: %d, Rehomed to versions: %d, Followed to archive: %d, Discarded duplicates: %d",
        result.moved,
        result.already_aligned,
        result.unmatched,
        result.ambiguous,
        result.collisions,
        result.copied_variants,
        result.ambiguous_variant_groups,
        result.variant_copy_errors,
        result.rehomed_to_variants,
        result.followed_to_archive,
        result.discarded_duplicates,
    )


def _follow_retired_videos(orphans: list[Path], video_index: dict[str, list[Path]],
                           trees: Trees) -> _FollowedRetired:
    unmatched: list[Path] = []
    followed_to_archive = 0
    rehomed_to_variants = 0
    collision_paths: list[str] = []
    discarded_duplicates = 0
    archived = _index_archived_videos(trees.archive) if orphans else {}
    for script_path in orphans:
        rehome = (_VersionRehome() if _waiting(script_path, trees)
                  else _rehome_to_library_version(script_path, video_index, archived, trees))
        if rehome.archived_copy:
            followed_to_archive += 1
        if rehome.moved:
            rehomed_to_variants += 1
            continue
        videos = archived.get(script_path.stem, [])
        if len(videos) != 1:
            log.info("UNMATCHED script (no video basename match): %s", script_path)
            if not _waiting(script_path, trees):
                unmatched.append(script_path)
            continue

        dest = videos[0].with_suffix(config.FUNSCRIPT_EXTENSION)
        if dest.exists():
            if _discard_or_keep_duplicate(script_path, dest) is _Duplicate.DISCARDED:
                discarded_duplicates += 1
            else:
                collision_paths.append(_shown(script_path, trees))
            continue

        try:
            shutil.move(str(script_path), str(dest))
        except OSError:
            log.exception("FAILED TO FOLLOW SCRIPT TO ARCHIVE  %s  ->  %s", script_path, dest)
            unmatched.append(script_path)
            continue
        carry_mark(script_path, dest)
        followed_to_archive += 1
        log.info("FOLLOW SCRIPT TO ARCHIVE  %s  ->  %s", script_path, dest)

    return _FollowedRetired(unmatched, followed_to_archive,
                            rehomed_to_variants, collision_paths, discarded_duplicates)


def _waiting(script_path: Path, trees: Trees) -> bool:
    return script_path.is_relative_to(trees.unmatched)


def _shown(script_path: Path, trees: Trees) -> str:
    if _waiting(script_path, trees):
        return str(script_path.relative_to(trees.unmatched.parent))
    return str(script_path.relative_to(trees.scripts))


def _park(script_path: Path, trees: Trees) -> str:
    dest = unique_path(trees.unmatched / script_path.name)
    try:
        trees.unmatched.mkdir(parents=True, exist_ok=True)
        shutil.move(str(script_path), str(dest))
    except OSError:
        log.exception("FAILED TO MOVE UNMATCHED SCRIPT  %s  ->  %s", script_path, dest)
        return _shown(script_path, trees)
    carry_mark(script_path, dest)
    log.info("MOVE UNMATCHED SCRIPT  %s  ->  %s", script_path, dest)
    return dest.name


def _rehome_to_library_version(script_path: Path, video_index: dict[str, list[Path]],
                               archived: dict[str, list[Path]],
                               trees: Trees) -> _VersionRehome:
    script_bucket = _version_bucket(
        trees.videos / script_path.relative_to(trees.scripts), trees)
    normalized = strip_processing_suffixes(script_path.stem)
    siblings = [
        video_path
        for matches in video_index.values()
        for video_path in matches
        if strip_processing_suffixes(video_path.stem) == normalized
        and _version_bucket(video_path, trees) == script_bucket
        and not script_path_for_video(video_path).exists()
    ]
    if not siblings:
        return _VersionRehome()

    archived_copy = False
    archived_videos = archived.get(script_path.stem, [])
    if len(archived_videos) == 1:
        archive_dest = archived_videos[0].with_suffix(config.FUNSCRIPT_EXTENSION)
        if not archive_dest.exists():
            try:
                shutil.copy2(script_path, archive_dest)
                archived_copy = True
                log.info("COPY SCRIPT TO ARCHIVE  %s  ->  %s", script_path, archive_dest)
            except OSError:
                log.exception("FAILED TO COPY SCRIPT TO ARCHIVE  %s  ->  %s", script_path, archive_dest)

    dest = script_path_for_video(min(siblings))
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(script_path), str(dest))
    except OSError:
        log.exception("FAILED TO REHOME SCRIPT TO VERSION  %s  ->  %s", script_path, dest)
        return _VersionRehome(archived_copy=archived_copy)
    carry_mark(script_path, dest)
    log.info("REHOME SCRIPT TO LIBRARY VERSION  %s  ->  %s", script_path, dest)
    return _VersionRehome(moved=True, archived_copy=archived_copy)


def _discard_or_keep_duplicate(script_path: Path, dest: Path) -> _Duplicate:
    if filecmp.cmp(str(script_path), str(dest), shallow=False):
        script_path.unlink()
        drop_mark(script_path)
        log.info("DISCARD DUPLICATE SCRIPT (archive already has it)  %s", script_path)
        return _Duplicate.DISCARDED
    log.warning("ARCHIVED SCRIPT COLLISION (destination exists and differs): %s -> %s", script_path, dest)
    return _Duplicate.COLLIDED


def _index_archived_videos(root: Path | None) -> dict[str, list[Path]]:
    if root is None or not root.is_dir():
        return {}
    index: dict[str, list[Path]] = defaultdict(list)
    for video_path in library_videos(root):
        index[video_path.stem].append(video_path)
    return index


def _index_videos(trees: Trees) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    for video_path in _library_videos(trees):
        index[video_path.stem].append(video_path)
    return index


def _library_videos(trees: Trees):
    if trees.videos.is_dir():
        yield from library_videos(trees.videos)
    for vr in lanes.vr_videos_kept_in(trees.vr, trees.videos):
        yield vr.in_library


def _iter_funscripts(*roots: Path):
    for root in roots:
        for path in root.rglob(f"*{config.FUNSCRIPT_EXTENSION}"):
            if path.is_file():
                yield path


def _matching_videos_for_script(script_path: Path, video_index: dict[str, list[Path]],
                                trees: Trees) -> list[Path]:
    matches = video_index.get(script_path.stem, [])
    kind = _filed_2d_kind(script_path, trees)
    if kind is None:
        return matches
    filed = {video_path: video_path.relative_to(trees.videos) for video_path in matches}
    matches = [video_path for video_path in matches if _ai_or_non_ai(filed[video_path]) == kind]
    source = _ai_filing(script_path.relative_to(trees.scripts)).source
    same_source = [video_path for video_path in matches
                   if _ai_filing(filed[video_path]).source == source]
    return same_source if source and same_source else matches


def _may_match_a_vr_video(script_path: Path, trees: Trees) -> bool:
    return _filed_2d_kind(script_path, trees) is None


def _filed_2d_kind(script_path: Path, trees: Trees) -> str | None:
    if not script_path.is_relative_to(trees.scripts):
        return None
    return _ai_or_non_ai(script_path.relative_to(trees.scripts))


def _ai_or_non_ai(rel: Path) -> str | None:
    match rel.parts:
        case ("2D", "AI" | "non_AI" as kind, *_):
            return kind
    return None


@dataclass(frozen=True)
class _AiFiling:
    source: str | None = None
    orientation: str | None = None


def _ai_filing(rel: Path) -> _AiFiling:
    match rel.parts[:-1]:
        case ("2D", "AI", "0_inbox", source, *_):
            return _AiFiling(source)
        case ("2D", "AI", "1_sorted", source, orientation, *_):
            return _AiFiling(source, orientation)
        case ("2D", "AI", "2_outbox", "upscaled_by_orientation", orientation, source, *_):
            return _AiFiling(source, orientation)
    return _AiFiling()


def _copy_missing_version_scripts(video_index: dict[str, list[Path]],
                                  trees: Trees) -> _VersionCopies:
    copied = 0
    ambiguous_groups = 0
    copy_error_paths: list[str] = []
    groups: dict[tuple[tuple[str, ...], str], list[Path]] = defaultdict(list)
    for matches in video_index.values():
        for video_path in matches:
            key = (_version_bucket(video_path, trees),
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
            source_video = _pick_version_source(target_video, existing_sources, trees)
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
                copy_error_paths.append(str(source_script.relative_to(trees.scripts)))
                log.exception("FAILED TO COPY VERSION SCRIPT  %s  ->  %s", source_script, dest_script)
                continue
            copied += 1
            existing_sources.append(target_video)
            log.info("COPY VERSION SCRIPT  %s  ->  %s", source_script, dest_script)

    return _VersionCopies(copied, ambiguous_groups, copy_error_paths)


def _pick_version_source(target_video: Path, existing_sources: list[Path],
                         trees: Trees) -> Path | None:
    ordered = sorted(
        existing_sources,
        key=lambda path: (
            _version_kind(path, trees) == _version_kind(target_video, trees),
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


def _version_bucket(video_path: Path, trees: Trees) -> tuple[str, ...]:
    rel = video_path.relative_to(trees.videos)
    filing = _ai_filing(rel)
    if filing.source and filing.orientation:
        return ("2D", "AI", filing.source, filing.orientation)
    match rel.parts:
        case ("2D", "non_AI", source, *_):
            return ("2D", "non_AI", source)
    return rel.parts[:2]


def _version_kind(video_path: Path, trees: Trees) -> str:
    rel = video_path.relative_to(trees.videos)
    match rel.parts:
        case ("2D", "AI", "1_sorted", *_):
            return "original"
        case ("2D", "AI", "2_outbox", *_):
            return "processed"
    return "processed" if "processed" in rel.parts else "original"


def _popup_message(result: ScriptsSyncResult) -> str:
    sections = []
    if result.unmatched_paths:
        sections.append(_naming(result.unmatched_paths, "matches no video", "match no video"))
    if result.ambiguous_paths:
        sections.append(_naming(result.ambiguous_paths,
                                "matches more than one video", "match more than one video"))
    if result.collision_paths:
        sections.append(_naming(
            result.collision_paths,
            "can't move into place, because a different script is already there",
            "can't move into place, because different scripts are already there"))
    if result.variant_copy_error_paths:
        sections.append(_naming(
            result.variant_copy_error_paths,
            "failed to copy to another version of its video",
            "failed to copy to other versions of their videos"))
    return "\n\n".join(sections)


def _naming(scripts: list[str], one_does: str, several_do: str) -> str:
    heading = f"This funscript {one_does}:" if len(scripts) == 1 else f"These funscripts {several_do}:"
    return "\n".join([heading, *sorted(scripts)])
