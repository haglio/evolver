from __future__ import annotations

import filecmp
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import config
from util import lanes, orientation, origenerator_gallery, provenance, script_library, sidecar
from util.ffprobe import orientation_of
from util.library_moves import move_with_its_records
from util.media_files import child_dirs, library_videos, remove_empty_dirs
from util.stage_result import StageResult

log = logging.getLogger(__name__)


@dataclass
class SortResult(StageResult):
    moved: int = 0
    deleted_collisions: int = 0
    made_again: int = 0
    skipped_unknown: int = 0
    moved_files: list[Path] = field(default_factory=list)


def run(*, inbox_dir: Path | None = None, sorted_dir: Path | None = None) -> SortResult:
    inbox_dir = config.INBOX_DIR if inbox_dir is None else inbox_dir
    sorted_dir = config.SORTED_DIR if sorted_dir is None else sorted_dir

    result = SortResult()
    sorted_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== Stage: 0_inbox -> 1_sorted (move) ===")
    log.info("INBOX:  %s", inbox_dir)
    log.info("SORTED: %s", sorted_dir)

    sources = list(child_dirs(inbox_dir))
    made_again = cache(origenerator_gallery.stems_made_again)
    if not sources:
        log.info("No source directories found in inbox: %s", inbox_dir)

    for src_root in sources:
        source = src_root.name

        log.info("--- Sorting source: %s ---", source)

        for src in library_videos(src_root):
            orient = orientation_of(src)

            if orient not in orientation.SORTED:
                log.info("UNKNOWN (leaving in inbox): %s", src)
                result.skipped_unknown += 1
                continue

            rel = src.relative_to(src_root)
            dest = sorted_dir / source / orient / rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            log.info("MOVE  [%s/%s] %s", source, orient, rel)
            remade = _the_copy_it_remakes(dest, src, source, made_again)
            if remade is not None:
                upscale = lanes.upscale_of(source, orient, dest.stem)
                if remade != dest:
                    _rename_to_the_remakes_name(
                        remade, dest, lanes.upscale_of(source, orient, remade.stem), upscale)
                _take_the_remake(src, dest, upscale)
                result.made_again += 1
                result.moved_files.append(dest)
            elif (played := _the_flick_it_remakes(src, source, orient, dest, made_again)) is not None:
                src.replace(dest)
                _make_way_for_the_remake(played, lanes.upscale_of(source, orient, dest.stem))
                result.made_again += 1
                result.moved_files.append(dest)
            elif _move_unique(src, dest):
                result.moved += 1
                result.moved_files.append(dest)
            else:
                result.deleted_collisions += 1

        remove_empty_dirs(src_root)

    log.info(
        "Sort done. Moved: %d, Made again: %d, Deleted collisions: %d, Unknown skipped: %d",
        result.moved, result.made_again, result.deleted_collisions, result.skipped_unknown,
    )
    return result


def _the_copy_it_remakes(dest: Path, handed_over: Path, source: str,
                         made_again: Callable[[], set[str]]) -> Path | None:
    if not lanes.sent_by_origenerator(source):
        return None
    if origenerator_gallery.generation_stem(handed_over.stem) not in made_again():
        return None
    copy = origenerator_gallery.the_one_version_in(dest.parent, dest.name)
    if copy is None or filecmp.cmp(handed_over, copy, shallow=False):
        return None
    return copy


def _the_flick_it_remakes(handed_over: Path, source: str, orient: str, dest: Path,
                          made_again: Callable[[], set[str]]) -> Path | None:
    if not lanes.is_genau_lane(source) or dest.exists():
        return None
    if origenerator_gallery.generation_stem(handed_over.stem) not in made_again():
        return None
    upscale = lanes.upscale_of(source, orient, dest.stem)
    return None if upscale is None else origenerator_gallery.the_one_version_in(upscale.parent, upscale.name)


def _make_way_for_the_remake(played: Path, upscale: Path) -> None:
    log.info("MADE AGAIN (to be upscaled in place of the flick Genau plays): %s", played)
    if played != upscale:
        move_with_its_records(played, upscale)
        sound = lanes.genau_sound_of(played)
        if sound.is_file():
            sound.replace(lanes.genau_sound_of(upscale))
    _upscale_again(upscale)


def _rename_to_the_remakes_name(old_copy: Path, dest: Path,
                                old_upscale: Path | None, upscale: Path | None) -> None:
    log.info("MADE AGAIN UNDER A NEW NAME (renaming its copies): %s  ->  %s", old_copy, dest)
    move_with_its_records(old_copy, dest)
    if old_upscale is not None and upscale is not None and old_upscale.exists() and not upscale.exists():
        move_with_its_records(old_upscale, upscale)


def _take_the_remake(src: Path, dest: Path, upscale: Path | None) -> None:
    log.info("MADE AGAIN (taking the place of its sorted copy): %s  ->  %s", src, dest)
    src.replace(dest)
    _carry_its_script(src, (dest,) if upscale is None else (dest, upscale))
    if upscale is not None:
        _upscale_again(upscale)


def _upscale_again(upscale: Path) -> None:
    try:
        record = sidecar.sidecar_path(upscale)
    except ValueError:
        return
    sidecar.update(record, _forget_what_made_the_copy_it_replaces)


def _forget_what_made_the_copy_it_replaces(current: dict) -> dict:
    return provenance.recorded(provenance.without(current, provenance.GENERATION),
                               provenance.UPSCALE, provenance.reconstructed(None))


def _carry_its_script(handed_over: Path, copies: tuple[Path, ...]) -> None:
    for script in (handed_over.with_suffix(config.FUNSCRIPT_EXTENSION),
                   script_library.script_path_for_video(handed_over)):
        if script.is_file():
            for copy in copies:
                copied_to = script_library.script_path_for_video(copy)
                script_library.copy_script(script, copied_to)
                script_library.mark_generated(copied_to)
            script_library.delete_script(script)
            return


def _move_unique(src: Path, dest: Path) -> bool:
    if not dest.exists():
        src.rename(dest)
        return True
    log.info("COLLISION (deleting inbox file): %s  ->  %s", src, dest)
    src.unlink()
    return False
