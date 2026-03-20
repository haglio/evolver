#!/usr/bin/env python3
"""Find likely duplicate videos by exact filesize within the non-AI library."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from util.windows_alert import show_error_window

log = logging.getLogger(__name__)


@dataclass
class DuplicateSizesResult:
    scanned_count: int
    duplicate_groups: dict[int, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.duplicate_groups


def iter_videos(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in config.VIDEO_EXTENSIONS:
            yield p


def run(show_popup: bool = False) -> DuplicateSizesResult:
    files = sorted(iter_videos(config.NON_AI_DIR))
    size_to_paths: dict[int, list[str]] = {}

    for file_path in files:
        relative_path = str(file_path.relative_to(config.NON_AI_DIR))
        size_to_paths.setdefault(file_path.stat().st_size, []).append(relative_path)

    duplicate_groups = {
        size: sorted(paths)
        for size, paths in size_to_paths.items()
        if size > 0 and len(paths) > 1
    }

    result = DuplicateSizesResult(
        scanned_count=len(files),
        duplicate_groups=dict(sorted(duplicate_groups.items())),
    )
    _log_result(result)

    if show_popup and not result.ok:
        log.info("Showing error popup for duplicate-size scan failure")
        show_error_window("Evolver - Likely Duplicate Videos", _popup_message(result))
        log.info("Error popup dismissed")

    return result


def _log_result(result: DuplicateSizesResult) -> None:
    log.info("=== Stage 4: duplicate-size scan ===")
    log.info("non_AI: %d video file(s) scanned in %s", result.scanned_count, config.NON_AI_DIR)

    for size, paths in result.duplicate_groups.items():
        log.error("LIKELY DUPLICATE SIZE: %d bytes", size)
        for path in paths:
            log.error("  -> %s", path)

    if result.ok:
        log.info("Stage 4 done. No likely duplicate non-AI videos found by exact filesize.")
    else:
        log.error("Stage 4 failed. See log entries above for likely duplicate non-AI videos.")


def _popup_message(result: DuplicateSizesResult) -> str:
    lines = [
        "Evolver found likely duplicate videos in non_AI.",
        "These files have the same exact filesize but different filenames.",
        "",
        "Check the log for full details:",
        str(config.LOG_FILE),
        "",
        f"non_AI files scanned: {result.scanned_count}",
        f"Duplicate-size groups found: {len(result.duplicate_groups)}",
    ]

    preview_lines: list[str] = []
    for size, paths in result.duplicate_groups.items():
        preview_lines.append(f"{size} bytes -> {', '.join(paths[:2])}")
        if len(preview_lines) == 10:
            break

    if preview_lines:
        lines.extend(["", *preview_lines])

    return "\n".join(lines)


def main() -> int:
    result = run(show_popup=False)

    print(f"non_AI : {result.scanned_count} video file(s)  in  {config.NON_AI_DIR}")
    print()

    if result.duplicate_groups:
        print(f"[DUPLICATE] {len(result.duplicate_groups)} exact-size duplicate group(s) found:")
        for size, paths in result.duplicate_groups.items():
            print(f"  Size: {size} bytes")
            for path in paths:
                print(f"    -> {path}")
        print()
        print(f"[FAIL] Likely duplicate non-AI videos found. See {config.LOG_FILE} for the full log.")
        return 1

    print("[OK] No likely duplicate non-AI videos found by exact filesize.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
