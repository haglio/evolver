#!/usr/bin/env python3
"""Verify 1_sorted and the active outbox set are in 1-to-1 correspondence."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from util.media_files import iter_finalized_videos
from util.windows_alert import show_error_window

log = logging.getLogger(__name__)


@dataclass
class CorrespondenceResult:
    sorted_count: int
    outbox_count: int
    orphan_outbox: list[str] = field(default_factory=list)
    orphan_sorted: list[str] = field(default_factory=list)
    duplicates: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not (self.orphan_outbox or self.orphan_sorted or self.duplicates or self.sorted_count != self.outbox_count)


def iter_videos(root: Path):
    yield from iter_finalized_videos(root, config.VIDEO_EXTENSIONS)


def sorted_to_outbox_name(sorted_file: Path) -> str:
    return f"{sorted_file.stem}_topaz{sorted_file.suffix}"


def run(show_popup: bool = False) -> CorrespondenceResult:
    sorted_files = sorted(iter_videos(config.SORTED_DIR))
    outbox_roots = config.active_outbox_dirs()
    outbox_files = []
    for root in outbox_roots:
        outbox_files.extend(iter_videos(root))
    outbox_files = sorted(outbox_files)

    expected_outbox_names = {sorted_to_outbox_name(p) for p in sorted_files}
    outbox_name_to_paths: dict[str, list[str]] = {}

    orphan_outbox: list[str] = []
    for outbox_file in outbox_files:
        root = next(root for root in outbox_roots if outbox_file.is_relative_to(root))
        relative_outbox = str(Path(root.name) / outbox_file.relative_to(root))
        outbox_name = outbox_file.name
        outbox_name_to_paths.setdefault(outbox_name, []).append(relative_outbox)
        if outbox_name not in expected_outbox_names:
            orphan_outbox.append(relative_outbox)

    orphan_sorted: list[str] = []
    for sorted_file in sorted_files:
        expected_outbox_name = sorted_to_outbox_name(sorted_file)
        if expected_outbox_name not in outbox_name_to_paths:
            orphan_sorted.append(str(sorted_file.relative_to(config.SORTED_DIR)))

    duplicates = {
        outbox_name: sorted(paths)
        for outbox_name, paths in outbox_name_to_paths.items()
        if len(paths) > 1
    }

    result = CorrespondenceResult(
        sorted_count=len(sorted_files),
        outbox_count=len(outbox_files),
        orphan_outbox=sorted(orphan_outbox),
        orphan_sorted=sorted(orphan_sorted),
        duplicates=duplicates,
    )
    _log_result(result)

    if show_popup and not result.ok:
        log.info("Showing error popup for correspondence failure")
        show_error_window("Evolver - Correspondence Error", _popup_message(result))
        log.info("Error popup dismissed")

    return result


def _log_result(result: CorrespondenceResult) -> None:
    log.info("=== Stage 8: correspondence check ===")
    log.info("1_sorted: %d video file(s) in %s", result.sorted_count, config.SORTED_DIR)
    log.info("Outboxes: %d video file(s) across %s", result.outbox_count, ", ".join(str(p) for p in config.active_outbox_dirs()))

    if result.sorted_count == result.outbox_count:
        log.info("Count check OK: %d files each", result.sorted_count)
    else:
        log.error("Count mismatch: %d sorted vs %d outbox", result.sorted_count, result.outbox_count)

    for orphan in result.orphan_outbox:
        log.error("ORPHAN OUTBOX: %s", orphan)

    for orphan in result.orphan_sorted:
        log.error("ORPHAN SORTED: %s", orphan)

    for outbox_name, paths in sorted(result.duplicates.items()):
        log.error("DUPLICATE OUTBOX NAME: %s", outbox_name)
        for path in paths:
            log.error("  -> %s", path)

    if result.ok:
        log.info("Stage 8 done. 1_sorted and the active outbox set are in perfect 1-to-1 correspondence.")
    else:
        log.error("Stage 8 failed. See log entries above for the mismatch details.")


def _popup_message(result: CorrespondenceResult) -> str:
    lines = [
        "Evolver found a 1_sorted / outbox correspondence problem.",
        "",
        f"Check the log for full details:",
        str(config.LOG_FILE),
        "",
        f"1_sorted files: {result.sorted_count}",
        f"Outbox files: {result.outbox_count}",
    ]

    if result.orphan_outbox:
        lines.extend([
            "",
            f"Outbox files without a matching source: {len(result.orphan_outbox)}",
            *_truncate(result.orphan_outbox),
        ])

    if result.orphan_sorted:
        lines.extend([
            "",
            f"Sorted files without a matching outbox file: {len(result.orphan_sorted)}",
            *_truncate(result.orphan_sorted),
        ])

    if result.duplicates:
        duplicate_lines = []
        for outbox_name, paths in sorted(result.duplicates.items()):
            duplicate_lines.append(f"{outbox_name} -> {', '.join(paths[:2])}")
            if len(duplicate_lines) == 10:
                break
        lines.extend([
            "",
            f"Duplicate outbox basenames found: {len(result.duplicates)}",
            *duplicate_lines,
        ])

    return "\n".join(lines)


def _truncate(items: list[str], limit: int = 10) -> list[str]:
    if len(items) <= limit:
        return items
    return [*items[:limit], "..."]


def main() -> int:
    result = run(show_popup=False)

    print(f"1_sorted  : {result.sorted_count} video file(s)  in  {config.SORTED_DIR}")
    print(f"outboxes  : {result.outbox_count} video file(s)  in  {', '.join(str(p) for p in config.active_outbox_dirs())}")
    print()

    if result.sorted_count == result.outbox_count:
        print(f"[OK] Counts match: {result.sorted_count} files each")
    else:
        print(f"[MISMATCH] Count difference: {result.sorted_count} sorted vs {result.outbox_count} outbox")

    print()

    if result.orphan_outbox:
        print(f"[ORPHAN-OUTBOX] {len(result.orphan_outbox)} outbox file(s) do not match '<sorted_name>_topaz.ext':")
        for item in result.orphan_outbox:
            print(f"  {item}")
        print()

    if result.orphan_sorted:
        print(f"[ORPHAN-SORTED] {len(result.orphan_sorted)} 1_sorted file(s) have no outbox counterpart:")
        for item in result.orphan_sorted:
            print(f"  {item}")
        print()

    if result.duplicates:
        print(f"[DUPLICATE] {len(result.duplicates)} duplicate outbox basename(s) found:")
        for outbox_name, paths in sorted(result.duplicates.items()):
            print(f"  Outbox name: {outbox_name}")
            for path in paths:
                print(f"    -> {path}")
        print()

    if result.ok:
        print("[OK] 1_sorted and the active outbox set are in perfect 1-to-1 correspondence.")
        return 0

    print(f"[FAIL] Correspondence issues found. See {config.LOG_FILE} for the full log.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
