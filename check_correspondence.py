#!/usr/bin/env python3
"""Verify 1_sorted and the active outbox set are in 1-to-1 correspondence."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from util.alert import show_error
from util.media_files import library_videos
from util.variants import UPSCALE_SUFFIX, upscaled_stem

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


def sorted_to_outbox_name(sorted_file: Path) -> str:
    return f"{upscaled_stem(sorted_file.stem)}{sorted_file.suffix}"


def run(
    show_popup: bool = False,
    *,
    sorted_dir: Path | None = None,
    outbox_dir: Path | None = None,
) -> CorrespondenceResult:
    """Check that every sorted video has exactly one upscale, and vice versa.

    The two trees compared are arguments, resolved here rather than in the
    signature: a default is evaluated at import, which would freeze the value
    past ``override_config``.
    """
    sorted_root = config.SORTED_DIR if sorted_dir is None else sorted_dir
    outbox_root = config.OUTBOX_DIR if outbox_dir is None else outbox_dir

    sorted_files = sorted(library_videos(sorted_root))
    outbox_files = sorted(library_videos(outbox_root))

    expected_outbox_names = {sorted_to_outbox_name(p) for p in sorted_files}
    outbox_name_to_paths: dict[str, list[str]] = {}

    orphan_outbox: list[str] = []
    for outbox_file in outbox_files:
        relative_outbox = str(Path(outbox_root.name) / outbox_file.relative_to(outbox_root))
        outbox_name = outbox_file.name
        outbox_name_to_paths.setdefault(outbox_name, []).append(relative_outbox)
        if outbox_name not in expected_outbox_names:
            orphan_outbox.append(relative_outbox)

    orphan_sorted: list[str] = []
    for sorted_file in sorted_files:
        expected_outbox_name = sorted_to_outbox_name(sorted_file)
        if expected_outbox_name not in outbox_name_to_paths:
            orphan_sorted.append(str(sorted_file.relative_to(sorted_root)))

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
    _log_result(result, sorted_root, outbox_root)

    if show_popup and not result.ok:
        log.info("Showing error popup for correspondence failure")
        show_error("Evolver - Correspondence Error", _popup_message(result))
        log.info("Error popup dismissed")

    return result


def _log_result(result: CorrespondenceResult, sorted_root: Path, outbox_root: Path) -> None:
    log.info("=== Stage: correspondence check ===")
    log.info("1_sorted: %d video file(s) in %s", result.sorted_count, sorted_root)
    log.info("Outboxes: %d video file(s) across %s", result.outbox_count, outbox_root)

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
        log.info("Correspondence check done. 1_sorted and the active outbox set are in perfect 1-to-1 correspondence.")
    else:
        log.error("Correspondence check failed. See log entries above for the mismatch details.")


def _popup_message(result: CorrespondenceResult) -> str:
    lines = [
        "Evolver found a 1_sorted / outbox correspondence problem.",
        "",
        "Check the log for full details:",
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
    sorted_root = config.SORTED_DIR
    outbox_root = config.OUTBOX_DIR
    result = run(show_popup=False, sorted_dir=sorted_root, outbox_dir=outbox_root)

    print(f"1_sorted  : {result.sorted_count} video file(s)  in  {sorted_root}")
    print(f"outboxes  : {result.outbox_count} video file(s)  in  {outbox_root}")
    print()

    if result.sorted_count == result.outbox_count:
        print(f"[OK] Counts match: {result.sorted_count} files each")
    else:
        print(f"[MISMATCH] Count difference: {result.sorted_count} sorted vs {result.outbox_count} outbox")

    print()

    if result.orphan_outbox:
        print(f"[ORPHAN-OUTBOX] {len(result.orphan_outbox)} outbox file(s) do not "
              f"match '<sorted_name>{UPSCALE_SUFFIX}.ext':")
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
