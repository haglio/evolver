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
from util.media_files import library_videos, remove_empty_dirs
from util.script_library import script_path_for_video
from util.variants import strip_processing_suffixes

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
    unmatched_paths: list[str] | None = None

    def __post_init__(self) -> None:
        if self.unmatched_paths is None:
            self.unmatched_paths = []

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

    unmatched_paths: list[str] = field(default_factory=list)
    followed_to_archive: int = 0
    rehomed_to_variants: int = 0
    collisions: int = 0
    discarded_duplicates: int = 0


@dataclass(frozen=True)
class Trees:
    """The three trees this stage aligns between, resolved once at its boundary.

    The script tree mirrors the video tree exactly, so almost everything here
    is one path read against the other, and where the archive is decides
    whether a script whose video left the library can follow it. Held as one
    record rather than read off ``config`` in each of the four bucket
    classifiers, which is what made a stage about two trees say nothing about
    which two.
    """

    videos: Path
    scripts: Path
    archive: Path | None


@dataclass(frozen=True)
class _VariantCopies:
    """What giving every scriptless variant its sibling's funscript came to."""

    copied: int = 0
    ambiguous_groups: int = 0
    copy_errors: int = 0


def run(show_popup: bool = False, *, video_dir: Path | None = None,
        script_dir: Path | None = None,
        archive_root: Path | None = None) -> ScriptsSyncResult:
    """Align the script tree to the video tree, and follow videos out of it.

    The three trees are arguments so the signature says what the stage reads
    and writes; see :class:`Trees`. They are resolved here rather than in the
    signature, in the sentinel form -- a default is evaluated at import, which
    would freeze the value past ``override_config``. The archive is the one
    that can genuinely be None: an unset one means a retired original stays in
    its bucket, so None cannot be told from "ask config" and the sentinel is
    the caller passing a path or not.
    """
    trees = Trees(
        videos=config.VIDEO_LIBRARY_DIR if video_dir is None else video_dir,
        scripts=config.SCRIPT_LIBRARY_DIR if script_dir is None else script_dir,
        archive=config.NONAI_RETIRED_ROOT if archive_root is None else archive_root,
    )
    result = ScriptsSyncResult()
    trees.scripts.mkdir(parents=True, exist_ok=True)

    log.info("=== Stage: scripts -> mirror video library ===")
    log.info("VIDEOS:  %s", trees.videos)
    log.info("SCRIPTS: %s", trees.scripts)

    video_index = _index_videos(trees.videos)

    orphans: list[Path] = []
    for script_path in _iter_funscripts(trees.scripts):
        matches = _matching_videos_for_script(script_path, video_index, trees)
        if not matches:
            orphans.append(script_path)
            continue
        if len(matches) > 1:
            log.warning("AMBIGUOUS script match for %s: %s", script_path, ", ".join(str(p) for p in matches))
            result.ambiguous += 1
            continue

        dest = script_path_for_video(matches[0])
        if script_path == dest:
            result.already_aligned += 1
            continue
        if dest.exists():
            log.warning("SCRIPT COLLISION (destination exists, leaving source in place): %s -> %s", script_path, dest)
            result.collisions += 1
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        log.info("MOVE SCRIPT  %s  ->  %s", script_path, dest)
        script_path.rename(dest)
        result.moved += 1

    followed = _follow_retired_videos(orphans, video_index, trees)
    result.unmatched += len(followed.unmatched_paths)
    result.unmatched_paths += followed.unmatched_paths
    result.followed_to_archive += followed.followed_to_archive
    result.rehomed_to_variants += followed.rehomed_to_variants
    result.collisions += followed.collisions
    result.discarded_duplicates += followed.discarded_duplicates
    remove_empty_dirs(trees.scripts)
    variants = _copy_missing_variant_scripts(video_index, trees)
    result.copied_variants += variants.copied
    result.ambiguous_variant_groups += variants.ambiguous_groups
    result.variant_copy_errors += variants.copy_errors
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
            show_error("Evolver - Funscript Match Error", _popup_message(result))
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
    unmatched_paths: list[str] = []
    followed_to_archive = 0
    rehomed_to_variants = 0
    collisions = 0
    discarded_duplicates = 0
    archived = _index_archived_videos(trees.archive) if orphans else {}
    for script_path in orphans:
        rehome = _rehome_to_library_variant(script_path, video_index, archived, trees)
        if rehome.archived_copy:
            followed_to_archive += 1
        if rehome.moved:
            rehomed_to_variants += 1
            continue
        videos = archived.get(script_path.stem, [])
        if len(videos) != 1:
            log.info("UNMATCHED script (no video basename match): %s", script_path)
            unmatched_paths.append(str(script_path.relative_to(trees.scripts)))
            continue

        dest = videos[0].with_suffix(config.FUNSCRIPT_EXTENSION)
        if dest.exists():
            if _discard_or_keep_duplicate(script_path, dest) is _Duplicate.DISCARDED:
                discarded_duplicates += 1
            else:
                collisions += 1
            continue

        try:
            # shutil, not Path.rename: the archive is a different drive from the
            # library — the whole point of it — and os.rename cannot cross one.
            shutil.move(str(script_path), str(dest))
        except OSError:
            log.exception("FAILED TO FOLLOW SCRIPT TO ARCHIVE  %s  ->  %s", script_path, dest)
            unmatched_paths.append(str(script_path.relative_to(trees.scripts)))
            continue
        followed_to_archive += 1
        log.info("FOLLOW SCRIPT TO ARCHIVE  %s  ->  %s", script_path, dest)

    return _FollowedRetired(unmatched_paths, followed_to_archive,
                            rehomed_to_variants, collisions, discarded_duplicates)


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


def _index_videos(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    if not root.is_dir():
        return index
    for video_path in library_videos(root):
        index[video_path.stem].append(video_path)
    return index


def _iter_funscripts(root: Path):
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
    copy_errors = 0
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
            except OSError:
                copy_errors += 1
                log.exception("FAILED TO COPY VARIANT SCRIPT  %s  ->  %s", source_script, dest_script)
                continue
            copied += 1
            existing_sources.append(target_video)
            log.info("COPY VARIANT SCRIPT  %s  ->  %s", source_script, dest_script)

    return _VariantCopies(copied, ambiguous_groups, copy_errors)


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
    rel = script_path.relative_to(trees.scripts)
    parts = rel.parts
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
    lines = [
        "Evolver found funscript files that do not cleanly match the video library.",
        "",
        "Check the log for full details:",
        str(config.LOG_FILE),
        "",
        f"Unmatched funscripts: {result.unmatched}",
        f"Ambiguous basename matches: {result.ambiguous}",
        f"Destination collisions: {result.collisions}",
        f"Variant copy errors: {result.variant_copy_errors}",
    ]
    return "\n".join(lines)
