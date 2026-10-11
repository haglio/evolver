"""Stage: repoint the suite's saved video references at videos that moved.

Evolver relocates videos — sorting them, retiring an upscaled original, and the
library gets reorganized by hand between runs too. Every sibling app that saved
a video's path (Genaumacher's clip bounds, Fun Time's favorites, watch counts and
where each player left each video) is left pointing at where the file used to
be, and so is the scene this app recorded each carved clip was found in. This
stage walks those stores each run and follows the move, and follows a renamed
folder into a setting that names it, Origenerator's sound folder, by the videos
the folder held (:mod:`util.folder_settings`).

Each of those files belongs to a repo that has never heard of this one, so a
format one of them changes would arrive here as a file that still parses and
still looks rewritable. A store whose shape this stage was not written for is
therefore left exactly as it is and reported for a person to look at
(:meth:`util.reference_stores.ReferenceStore.shape_complaint`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import config
from util import folder_settings, reference_stores, video_locator
from util.media_files import reachable

log = logging.getLogger(__name__)


@dataclass
class ReferenceSyncResult:
    checked: int = 0
    relocated: int = 0
    unresolved: int = 0
    not_checked: int = 0
    write_errors: int = 0
    refused: int = 0

    @property
    def ok(self) -> bool:
        return not self.write_errors

    @property
    def needs_an_eye(self) -> bool:
        """A sibling's file is no longer the shape this stage was written for.

        Not a failure: leaving it alone is this stage doing its job. It is a
        person's to look at, because until somebody does, the references in
        that file stop following the videos they point at.
        """
        return bool(self.refused)


@dataclass(frozen=True)
class _Reconciled:
    """What following one store's references came to."""

    checked: int = 0
    relocated: int = 0
    unresolved: int = 0
    not_checked: int = 0
    write_errors: int = 0
    refused: int = 0


def run() -> ReferenceSyncResult:
    result = ReferenceSyncResult()
    log.info("=== Stage: follow videos that moved ===")

    unreachable = [folder for folder in (config.VR_VIDEO_DIR, config.NONAI_RETIRED_ROOT)
                   if folder is not None and not reachable(folder)]
    index = video_locator.build_index()
    reconciled = [_reconcile(store, index, unreachable) for store in reference_stores.discover()]
    reconciled += [_follow(setting, index) for setting in folder_settings.discover()]
    for one in reconciled:
        result.checked += one.checked
        result.relocated += one.relocated
        result.unresolved += one.unresolved
        result.not_checked += one.not_checked
        result.write_errors += one.write_errors
        result.refused += one.refused

    log.info(
        "References done. Checked: %d, Relocated: %d, Unresolved: %d, Write errors: %d, "
        "Refused: %d",
        result.checked,
        result.relocated,
        result.unresolved,
        result.write_errors,
        result.refused,
    )
    if result.not_checked:
        log.warning("%d reference(s) not checked: %s cannot be reached.",
                    result.not_checked, " and ".join(str(folder) for folder in unreachable))
    return result


def _reconcile(
    store: reference_stores.ReferenceStore,
    index: dict[str, list[Path]],
    unreachable: list[Path],
) -> _Reconciled:
    complaint = store.shape_complaint()
    if complaint is not None:
        return _refused(store.label, store.path, complaint)

    references = store.read()

    moves: dict[str, str] = {}
    unresolved = 0
    not_checked = 0
    for reference in references:
        was_at = Path(reference)
        if any(was_at.is_relative_to(folder) for folder in unreachable):
            not_checked += 1
            continue
        if was_at.exists():
            continue
        now_at = (video_locator.relocate(was_at, index)
                  or _another_version(store, was_at, index)
                  or _renamed(store, was_at))
        if now_at is None:
            unresolved += 1
            log.warning("UNRESOLVED %s reference (%s): %s", store.label, store.path.name, reference)
            continue
        moves[reference] = str(now_at)
        log.info("REPOINT %s  %s  ->  %s", store.label, reference, now_at)

    relocated = 0
    write_errors = 0
    if moves:
        try:
            store.rewrite(moves)
        except OSError:
            log.exception("FAILED TO REWRITE %s (%s)", store.label, store.path)
            write_errors = 1
        else:
            relocated = len(moves)
    return _Reconciled(checked=len(references), relocated=relocated,
                       unresolved=unresolved, not_checked=not_checked,
                       write_errors=write_errors)


def _follow(setting: folder_settings.FolderSetting, index: dict[str, list[Path]]) -> _Reconciled:
    complaint = setting.shape_complaint()
    if complaint is not None:
        return _refused(setting.label, setting.path, complaint)
    folder = setting.folder()
    if folder is None or not reachable(folder):
        return _Reconciled()
    if folder.is_dir():
        folder_settings.remember(setting.label, folder, folder_settings.held(folder))
        return _Reconciled(checked=1)

    now_at = video_locator.relocate_folder(folder_settings.remembered(setting.label, folder), index)
    if now_at is None:
        log.warning("UNRESOLVED %s (%s): %s", setting.label, setting.path.name, folder)
        return _Reconciled(checked=1, unresolved=1)
    try:
        setting.repoint(now_at)
    except OSError:
        log.exception("FAILED TO REWRITE %s (%s)", setting.label, setting.path)
        return _Reconciled(checked=1, write_errors=1)
    folder_settings.remember(setting.label, now_at, folder_settings.held(now_at))
    log.info("REPOINT %s  %s  ->  %s", setting.label, folder, now_at)
    return _Reconciled(checked=1, relocated=1)


def _refused(label: str, path: Path, complaint: str) -> _Reconciled:
    log.warning(
        "REFUSING %s (%s): %s. Its references are not being followed until "
        "this stage is taught the new shape.",
        label, path.name, complaint,
    )
    return _Reconciled(refused=1)


def _another_version(
    store: reference_stores.ReferenceStore, was_at: Path, index: dict[str, list[Path]],
) -> Path | None:
    if not store.any_version_will_do:
        return None
    return video_locator.another_version_of(was_at, index)


def _renamed(store: reference_stores.ReferenceStore, was_at: Path) -> Path | None:
    """Last resort: the video is still where it was, under a name it no longer has."""
    fingerprint = store.fingerprint()
    if fingerprint is None or not was_at.parent.is_dir():
        return None
    return video_locator.renamed_in_place(was_at, fingerprint)
