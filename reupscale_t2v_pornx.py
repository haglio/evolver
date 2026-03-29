"""One-time script: move t2v provider videos back to inbox for re-upscaling.

Deletes _topaz.mp4 files from 2_outbox and moves source files from
1_sorted back to 0_inbox/provider/ so the pipeline re-processes them
with the new prob-4 upscale filter.

Run with --dry-run first to preview what will happen.
"""

import json
import shutil
import sys
from pathlib import Path

import config


def main():
    dry_run = "--dry-run" in sys.argv

    meta_root = config.METADATA_DIR / "2_outbox" / "upscaled_by_orientation"
    outbox_root = config.OUT_UPSCALED_DIR
    sorted_root = config.SORTED_DIR
    inbox_root = config.INBOX_DIR

    deleted_outbox = 0
    moved_to_inbox = 0
    skipped_no_outbox = 0
    errors = []

    for json_path in sorted(meta_root.rglob("*.json")):
        parts = json_path.relative_to(meta_root).parts
        if len(parts) < 3 or parts[1] != "provider":
            continue
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "source_image" in payload:
            continue

        orient, source = parts[0], parts[1]
        topaz_name = json_path.stem + ".mp4"
        source_stem = json_path.stem.replace("_topaz", "")

        # Only process if outbox file exists (nothing to re-upscale otherwise)
        outbox_file = outbox_root / orient / source / topaz_name
        if not outbox_file.exists():
            skipped_no_outbox += 1
            continue

        if dry_run:
            print(f"DELETE {outbox_file}")
        else:
            outbox_file.unlink()
        deleted_outbox += 1

        # Move sorted file back to inbox
        sorted_file = None
        for ext in config.VIDEO_EXTENSIONS:
            candidate = sorted_root / source / orient / (source_stem + ext)
            if candidate.exists():
                sorted_file = candidate
                break

        if sorted_file:
            inbox_dir = inbox_root / source
            dest = inbox_dir / sorted_file.name
            if dest.exists():
                errors.append(f"COLLISION: {sorted_file} -> {dest}")
            else:
                if dry_run:
                    print(f"MOVE   {sorted_file} -> {dest}")
                else:
                    inbox_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(sorted_file), str(dest))
                moved_to_inbox += 1

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}Deleted from outbox: {deleted_outbox}")
    print(f"{prefix}Moved to inbox: {moved_to_inbox}")
    if skipped_no_outbox:
        print(f"Skipped (no outbox file): {skipped_no_outbox}")
    if errors:
        print(f"Errors: {len(errors)}")
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
