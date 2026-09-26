"""Stage: align .funscript files to mirror the video library tree."""
from __future__ import annotations

import filecmp
import logging
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

import config
from util.alert import show_error
from util.media_files import library_videos, listed_videos, remove_empty_dirs, unique_path
from util.script_library import (
    carry_mark,
    copy_mark,
    drop_mark,
    remove_empty_mark_folders,
    script_path_for_video,
)
from util.variants import strip_processing_suffixes

log = logging.getLogger(__name__)

VR_FOLDER = "VR"


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
    unmatched_paths: list[str] = field(default_factory=list)
    ambiguous_paths: list[str] = field(default_factory=list)
    collision_paths: list[str] = field(default_factory=list)
    variant_copy_error_paths: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.unmatched or self.ambiguous or self.collisions or self.variant_copy_errors)


class _Duplicate(Enum):
    """What became of a script whose archived video already had one."""

    DISCARDED = auto()
    COLLIDED = auto()


@dataclass(frozen=True)
class _VariantRehome:
    """What sending an orphan script to a library variant came to.

    The two are independent: the archived original can get its self-describing
    copy and the move to the variant still fail.
    """

    moved: bool = False
    archived_copy: bool = False


@dataclass(frozen=True)
class _FollowedRetired:
    """What became of the scripts whose videos are no longer in the library."""

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


@dataclass(frozen=True)
class _VariantCopies:
    """What giving every scriptless variant its sibling's funscript came to."""

    copied: int = 0
    ambiguous_groups: int = 0
    copy_error_paths: list[str] = field(default_factory=list)


def run(show_popup: bool = False, *, video_dir: Path | None = None,
        script_dir: Path | None = None, unmatched_dir: Path | None = None,
        archive_root: Path | None = None, vr_dir: Path | None = None) -> ScriptsSyncResult:
    """Align the script tree to the video tree, follow videos out of it, and move
    what matches no video to unmatched_scripts until it is renamed.

    The folders are arguments so the signature says what the stage reads and
    writes; see :class:`Trees`. They are resolved here rather than in the
    signature, in the sentinel form -- a default is evaluated at import, which
    would freeze the value past ``override_config``. The archive and the VR
    videos' own folder are the ones that can genuinely be None, an unset one
    meaning there is none, so None cannot be told from "ask config" and the
    sentinel is the caller passing a path or not.
    """
    trees = Trees(
        videos=config.VIDEO_LIBRARY_DIR if video_dir is None else video_dir,
        scripts=config.SCRIPT_LIBRARY_DIR if script_dir is None else script_dir,
        unmatched=config.UNMATCHED_SCRIPTS_DIR if unmatched_dir is None else unmatched_dir,
        archive=config.NONAI_RETIRED_ROOT if archive_root is None else archive_root,
        vr=config.VR_VIDEO_DIR if vr_dir is None else vr_dir,
    )
    result = ScriptsSyncResult()
    trees.scripts.mkdir(parents=True, exist_ok=True)

    log.info("=== Stage: scripts -> mirror video library ===")
    log.info("VIDEOS:  %s", trees.videos)
    log.info("SCRIPTS: %s", trees.scripts)

    video_index = _index_videos(trees)

    orphans: list[Path] = []
    for script_path in _iter_funscripts(trees.scripts, trees.unmatched):
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

    followed = _follow_retired_videos(orphans, video_index, trees)
    result.unmatched_paths += [_park(script_path, trees) for script_path in followed.unmatched]
    result.followed_to_archive += followed.followed_to_archive
    result.rehomed_to_variants += followed.rehomed_to_variants
    result.collision_paths += followed.collision_paths
    result.discarded_duplicates += followed.discarded_duplicates
    remove_empty_dirs(trees.scripts)
    remove_empty_mark_folders()
    variants = _copy_missing_variant_scripts(video_index, trees)
    result.copied_variants += variants.copied
    result.ambiguous_variant_groups += variants.ambiguous_groups
    result.variant_copy_error_paths += variants.copy_error_paths
    result.unmatched = len(result.unmatched_paths)
    result.ambiguous = len(result.ambiguous_paths)
    result.collisions = len(result.collision_paths)
    result.variant_copy_errors = len(result.variant_copy_error_paths)
    log.info(
        "Scripts sync done. Moved: %d, Already aligned: %d, Unmatched: %d, Ambiguous: %d, Collisions: %d, Variant copies: %d, Ambiguous variant groups: %d, Variant copy errors: %d, Rehomed to variants: %d, Followed to archive: %d, Discarded duplicates: %d",
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
    if not result.ok:
        log.error("Scripts sync failed. See log entries above for unresolved funscript alignment issues.")
        if show_popup:
            log.info("Showing error popup for scripts-sync failure")
            links = [("Open unmatched_scripts", trees.unmatched)] if result.unmatched_paths else []
            show_error("Evolver - Funscript Match Error", _popup_message(result), links=links)
            log.info("Error popup dismissed")
    return result


def _follow_retired_videos(orphans: list[Path], video_index: dict[str, list[Path]],
                           trees: Trees) -> _FollowedRetired:
    """Send each script whose video left the library for the archive after it.

    With one exception, checked first: when an upscaled sibling of the retired
    video is still IN the library (upscaling archives the original and leaves
    the new variant scriptless), the script's real home is that sibling — one
    funscript serves every variant of a video. The library copy moves to the
    sibling's mirror path, and the archived original merely keeps a duplicate
    beside it for self-description.

    A retired original is moved out of the library entirely (see
    :func:`util.nonai_retire._archive_original`) and its funscript goes with
    it, because the script tree mirrors only the library: a video outside it has
    to describe itself, script beside it rather than in a tree that no longer
    covers it. This stage follows rather than trusting the retiring to have done
    it, because the archive also fills by hand: a funscript stranded by a
    video swept in matches no video, fails this stage, and would fail it
    identically on every run afterward.

    Only a stem that names exactly one archived video is followed. Two of them
    is a guess about which video the script belongs to, and no archived video at
    all is the real unmatched case this stage exists to report.
    """
    unmatched: list[Path] = []
    followed_to_archive = 0
    rehomed_to_variants = 0
    collision_paths: list[str] = []
    discarded_duplicates = 0
    archived = _index_archived_videos(trees.archive) if orphans else {}
    for script_path in orphans:
        rehome = (_VariantRehome() if _waiting(script_path, trees)
                  else _rehome_to_library_variant(script_path, video_index, archived, trees))
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
            # shutil, not Path.rename: the archive is a different drive from the
            # library — the whole point of it — and os.rename cannot cross one.
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


def _rehome_to_library_variant(script_path: Path, video_index: dict[str, list[Path]],
                               archived: dict[str, list[Path]],
                               trees: Trees) -> _VariantRehome:
    """Move an orphan script to a still-in-library variant of its video.

    The scriptless sibling is found by the same normalized-stem-within-bucket
    rule the variant-copy pass uses; the archived original, when it is
    unambiguous and bare, gets a copy before the move so it can still describe
    itself.
    """
    script_bucket = _variant_bucket(
        trees.videos / script_path.relative_to(trees.scripts), trees)
    normalized = strip_processing_suffixes(script_path.stem)
    siblings = [
        video_path
        for matches in video_index.values()
        for video_path in matches
        if strip_processing_suffixes(video_path.stem) == normalized
        and _variant_bucket(video_path, trees) == script_bucket
        and not script_path_for_video(video_path).exists()
    ]
    if not siblings:
        return _VariantRehome()

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

    dest = script_path_for_video(sorted(siblings)[0])
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(script_path), str(dest))
    except OSError:
        log.exception("FAILED TO REHOME SCRIPT TO VARIANT  %s  ->  %s", script_path, dest)
        return _VariantRehome(archived_copy=archived_copy)
    carry_mark(script_path, dest)
    log.info("REHOME SCRIPT TO LIBRARY VARIANT  %s  ->  %s", script_path, dest)
    return _VariantRehome(moved=True, archived_copy=archived_copy)


def _discard_or_keep_duplicate(script_path: Path, dest: Path) -> _Duplicate:
    """Delete the stranded script when the archived video already has its own.

    Two library scripts can name the same archived video — the same funscript
    filed under both a "1 could use work" and a "2 do not need work" folder, say
    — so the second one arrives to find the destination taken by the first.
    Byte-identical means nothing is lost by dropping it: the content is already
    sitting beside the video. Anything else is a genuine conflict, and the two
    versions are left for a person to judge.
    """
    if filecmp.cmp(str(script_path), str(dest), shallow=False):
        script_path.unlink()
        drop_mark(script_path)
        log.info("DISCARD DUPLICATE SCRIPT (archive already has it)  %s", script_path)
        return _Duplicate.DISCARDED
    log.warning("ARCHIVED SCRIPT COLLISION (destination exists and differs): %s -> %s", script_path, dest)
    return _Duplicate.COLLIDED


def _index_archived_videos(root: Path | None) -> dict[str, list[Path]]:
    """Archived videos by basename — empty when no archive is configured.

    Built only when some script went unmatched, so an ordinary run never walks
    the archive drive.
    """
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
    if trees.vr is not None:
        for kept in listed_videos(trees.vr):
            yield trees.videos / VR_FOLDER / kept.relative_to(trees.vr)


def _iter_funscripts(*roots: Path):
    for root in roots:
        for path in root.rglob(f"*{config.FUNSCRIPT_EXTENSION}"):
            if path.is_file():
                yield path


def _matching_videos_for_script(script_path: Path, video_index: dict[str, list[Path]],
                                trees: Trees) -> list[Path]:
    matches = video_index.get(script_path.stem, [])
    bucket = _script_match_bucket(script_path, trees)
    if bucket is None:
        return matches
    return [video_path for video_path in matches
            if _video_match_bucket(video_path, trees) == bucket]


def _copy_missing_variant_scripts(video_index: dict[str, list[Path]],
                                  trees: Trees) -> _VariantCopies:
    copied = 0
    ambiguous_groups = 0
    copy_error_paths: list[str] = []
    groups: dict[tuple[tuple[str, ...], str], list[Path]] = defaultdict(list)
    for matches in video_index.values():
        for video_path in matches:
            key = (_variant_bucket(video_path, trees),
                   strip_processing_suffixes(video_path.stem))
            groups[key].append(video_path)

    for (_, normalized_stem), videos in sorted(groups.items()):
        if len(videos) < 2:
            continue

        missing_targets = [video for video in videos if not script_path_for_video(video).exists()]
        if not missing_targets:
            continue

        existing_sources = [video for video in videos if script_path_for_video(video).exists()]
        if not existing_sources:
            continue

        for target_video in sorted(missing_targets):
            source_video = _pick_variant_source(target_video, existing_sources, trees)
            if source_video is None:
                log.warning(
                    "AMBIGUOUS VARIANT SCRIPT GROUP for stem %s: %s",
                    normalized_stem,
                    ", ".join(str(script_path_for_video(video)) for video in sorted(existing_sources)),
                )
                ambiguous_groups += 1
                continue

            source_script = script_path_for_video(source_video)
            dest_script = script_path_for_video(target_video)
            try:
                dest_script.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_script, dest_script)
                copy_mark(source_script, dest_script)
            except OSError:
                copy_error_paths.append(str(source_script.relative_to(trees.scripts)))
                log.exception("FAILED TO COPY VARIANT SCRIPT  %s  ->  %s", source_script, dest_script)
                continue
            copied += 1
            existing_sources.append(target_video)
            log.info("COPY VARIANT SCRIPT  %s  ->  %s", source_script, dest_script)

    return _VariantCopies(copied, ambiguous_groups, copy_error_paths)


def _pick_variant_source(target_video: Path, existing_sources: list[Path],
                         trees: Trees) -> Path | None:
    ordered = sorted(
        existing_sources,
        key=lambda path: (
            _variant_kind(path, trees) == _variant_kind(target_video, trees),
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


def _variant_bucket(video_path: Path, trees: Trees) -> tuple[str, ...]:
    rel = video_path.relative_to(trees.videos)
    parts = rel.parts
    if len(parts) >= 6 and parts[0] == "2D" and parts[1] == "AI":
        if parts[2] == "1_sorted":
            return ("2D", "AI", parts[3], parts[4])
        if parts[2] == "2_outbox" and parts[3] == "upscaled_by_orientation":
            return ("2D", "AI", parts[5], parts[4])
    if len(parts) >= 3 and parts[0] == "2D" and parts[1] == "non_AI":
        return tuple(parts[:3])
    return tuple(parts[:2]) if len(parts) >= 2 else tuple(parts)


def _variant_kind(video_path: Path, trees: Trees) -> str:
    rel = video_path.relative_to(trees.videos)
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "2D" and parts[1] == "AI":
        if parts[2] == "1_sorted":
            return "original"
        if parts[2] == "2_outbox":
            return "processed"
    if "processed" in parts:
        return "processed"
    return "original"


def _script_match_bucket(script_path: Path, trees: Trees) -> str | None:
    if not script_path.is_relative_to(trees.scripts):
        return None
    parts = script_path.relative_to(trees.scripts).parts
    if len(parts) >= 2 and parts[0] == "2D" and parts[1] in {"AI", "non_AI"}:
        return parts[1]
    return None


def _video_match_bucket(video_path: Path, trees: Trees) -> str | None:
    rel = video_path.relative_to(trees.videos)
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "2D" and parts[1] in {"AI", "non_AI"}:
        return parts[1]
    return None


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
