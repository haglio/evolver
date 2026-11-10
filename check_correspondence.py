from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app_support.trash_names import name_before_trash

import config
from util import lanes
from util.alert import show_error
from util.media_files import library_videos
from util.sidecar import sidecar_folder
from util.stage_result import StageResult
from util.versions import upscaled_stem

log = logging.getLogger(__name__)

_LISTED = 10
_PCLOUD_CONFLICT_COPY = re.compile(r" \[conflicted( \d+)?\]$")


@dataclass
class CorrespondenceResult(StageResult):
    sorted_count: int
    upscale_count: int
    orphan_upscales: list[str] = field(default_factory=list)
    orphan_sorted: list[str] = field(default_factory=list)
    duplicates: dict[str, list[str]] = field(default_factory=dict)
    missing_flicks: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.orphan_upscales or self.orphan_sorted or self.duplicates or self.missing_flicks)


def upscale_name(sorted_file: Path) -> str:
    return f"{upscaled_stem(sorted_file.stem)}{sorted_file.suffix}"


@dataclass(frozen=True)
class _Lane:
    sorted_copies: list[Path]
    upscales: list[Path]
    kept_once_sorted_copy_retired: bool


def _lanes(sorted_by_source: dict[Path, str]) -> list[_Lane]:
    return [_Lane([copy for copy, source in sorted_by_source.items() if lane.is_for(source)],
                  [] if lane.upscales is None
                  else [*library_videos(lane.upscales), *library_videos(lane.trash)],
                  kept_once_sorted_copy_retired=lane.genau)
            for lane in lanes.upscale_lanes()]


def _shown(path: Path) -> str:
    try:
        return str(path.relative_to(config.LIBRARY_ROOT))
    except ValueError:
        return str(path)


def run(show_popup: bool = False) -> CorrespondenceResult:
    sorted_root = config.SORTED_DIR
    sorted_by_source = {copy: copy.relative_to(sorted_root).parts[0]
                        for copy in sorted(library_videos(sorted_root))}
    sorted_files = list(sorted_by_source)
    made: set[str] = set()
    upscale_count = 0
    duplicates: dict[str, list[str]] = {}
    orphan_upscales: list[str] = []
    orphan_sorted: list[str] = []
    for lane in _lanes(sorted_by_source):
        expected = {upscale_name(p) for p in lane.sorted_copies}
        by_name: dict[str, list[str]] = {}
        for upscale in sorted(lane.upscales):
            name = name_before_trash(upscale.name)
            by_name.setdefault(name, []).append(_shown(upscale))
            if name not in expected and not lane.kept_once_sorted_copy_retired:
                orphan_upscales.append(_shown(upscale))
        orphan_sorted += [str(p.relative_to(sorted_root)) for p in lane.sorted_copies
                          if upscale_name(p) not in by_name]
        made |= set(by_name)
        upscale_count += len(lane.upscales)
        duplicates |= {name: sorted(paths) for name, paths in by_name.items() if len(paths) > 1}

    result = CorrespondenceResult(
        sorted_count=len(sorted_files),
        upscale_count=upscale_count,
        orphan_upscales=sorted(orphan_upscales),
        orphan_sorted=sorted(orphan_sorted),
        duplicates=duplicates,
        missing_flicks=_flicks_whose_record_outlived_them(
            made, {upscale_name(p) for p in sorted_files}),
    )
    _log_result(result)

    if show_popup and not result.ok:
        log.info("Showing error popup for correspondence failure")
        show_error("Evolver - Correspondence Error", _popup_message(result))
        log.info("Error popup closed")

    return result


def _flicks_whose_record_outlived_them(present: set[str], awaited: set[str]) -> list[str]:
    genau = lanes.genau_delivery_dir()
    records = None if genau is None else sidecar_folder(genau)
    if records is None or not records.is_dir():
        return []
    return sorted(_shown(genau / f"{record.stem}.mp4") for record in records.glob("*.json")
                  if not _PCLOUD_CONFLICT_COPY.search(record.stem)
                  and f"{record.stem}.mp4" not in present | awaited)


def _log_result(result: CorrespondenceResult) -> None:
    log.info("=== Stage: correspondence check ===")
    log.info("1_sorted: %d video file(s)", result.sorted_count)
    log.info("Upscales: %d video file(s) in the Kino and Genau folders and their trash",
             result.upscale_count)
    for orphan in result.orphan_upscales:
        log.error("UPSCALE WITHOUT ITS 1_SORTED VIDEO: %s", orphan)
    for orphan in result.orphan_sorted:
        log.error("1_SORTED VIDEO WITHOUT ITS UPSCALE: %s", orphan)
    for name, paths in sorted(result.duplicates.items()):
        log.error("UPSCALE NAME IN MORE THAN ONE PLACE: %s", name)
        for path in paths:
            log.error("  -> %s", path)
    for missing in result.missing_flicks:
        log.error("MISSING FROM GENAU'S FOLDER (its record is still there): %s", missing)

    if result.ok:
        log.info("Correspondence check done. Every 1_sorted video has its upscale, and no upscale is missing.")
    else:
        log.error("Correspondence check failed. See log entries above for the mismatch details.")


def _popup_message(result: CorrespondenceResult) -> str:
    lines = [
        "Evolver found 1_sorted videos and upscales that do not match.",
        "",
        "Check the log for full details:",
        str(config.LOG_FILE),
        "",
        f"1_sorted videos: {result.sorted_count}",
        f"Upscales in the Kino and Genau folders: {result.upscale_count}",
    ]
    sections = (
        ("Upscales without their 1_sorted video", result.orphan_upscales),
        ("1_sorted videos without their upscale", result.orphan_sorted),
        ("Upscale names in more than one place",
         [f"{name} -> {', '.join(paths[:2])}" for name, paths in sorted(result.duplicates.items())]),
        (f"Genau {config.GENAU_FLICKS_WORD} missing from Genau's folder", result.missing_flicks),
    )
    for heading, items in sections:
        if items:
            lines.extend(["", f"{heading}: {len(items)}", *_truncate(items)])
    return "\n".join(lines)


def _truncate(items: list[str]) -> list[str]:
    if len(items) <= _LISTED:
        return items
    return [*items[:_LISTED], "..."]


def main() -> int:
    result = run(show_popup=False)
    print(_popup_message(result))
    if result.ok:
        print("\n[OK] Every 1_sorted video has its upscale, and no upscale is missing.")
        return 0
    print("\n[FAIL] Correspondence issues found.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
