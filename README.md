# Evolver

Evolver is a Windows-scheduled video pipeline that runs every 15 minutes and:

1. Sorts videos from `0_inbox/<source>/` into `1_sorted/<source>/<orientation>/`
2. Purges `kinda_weird/` outputs from the active outbox set — normally `2_outbox`, and both `2_outbox` plus `3_new_outbox` while regeneration mode is enabled. It also deletes each weird file's corresponding source from `1_sorted/`. A Windows error dialog pops up if any source file cannot be found.
3. Rehomes `.funscript` files under `videos/scripts/scripts` so they mirror the matched video path under `videos/videos`. A script only moves when there is exactly one basename match in the same library lane; scripts under `2D/AI` only consider `2D/AI` videos, and scripts under `2D/non_AI` only consider `2D/non_AI` videos. Unmatched or ambiguous names are logged and left alone. After that, Evolver also copies missing funscripts across matching processed/original video variants, including `1_sorted` <-> `2_outbox` / `3_new_outbox` `_topaz` pairs and matching `processed` <-> non-processed variants within the same source bucket. Finally, any AI video that has a funscript under `videos/scripts/scripts/2D/AI` is duplicated into `videos/videos/2D/non_AI/actually_AI_but_funscripted`, preserving its relative subfolders, so Fun Time's primary VLC window can pick it up.
4. Syncs `fun_time/favs.csv` into a `Fun Time Favs` folder on the Chrome bookmarks bar for the Chrome profile whose visible name is `Blair`. Only the `web_url` column is used, and each run replaces that folder's contents with the current CSV URLs.
5. Upscales/interpolates sorted videos using Topaz Video AI ffmpeg. Work is now capped per scheduler run, newly sorted inbox files are processed first, and any remaining batch slots can be used for regeneration backlog.
6. Scans `1_sorted` for likely accidental duplicates: video files with the same exact filesize but different filenames, with a Windows error dialog if any are found
7. Runs a final 1-to-1 correspondence check between `1_sorted` and the active outbox set, where each sorted file must have an outbox counterpart named `<sorted_stem>_topaz<ext>`, with a Windows error dialog if mismatches remain

`<source>` is discovered dynamically from directory names. Any new subdirectory under `0_inbox` is treated as a source automatically, and matching output directories are created on demand.

## Current architecture

- Scheduler: Windows Task Scheduler task `evolver` (15-minute trigger)
- Launcher: `evolver.ps1` (hidden, non-interactive)
- Pipeline entry point: `evolver.py`
- Modules:
  - `config.py` - paths and settings
  - `tasks/sort.py` - Stage 1 inbox sorting
  - `tasks/purge_weird.py` - Stage 2 kinda_weird cleanup
- `tasks/scripts_sync.py` - Stage 3 funscript/video tree alignment, processed/original variant copying, and AI-video duplication for Fun Time's primary VLC window
  - `tasks/upscale.py` - Stage 4 Topaz processing
  - `check_duplicate_sizes.py` - Stage 5 duplicate-size scan for likely source duplicates
  - `check_correspondence.py` - Stage 6 integrity verification and one-time manual check
  - `util/ffprobe.py` - orientation probing

## Requirements

- Windows
- Python 3.14+ (currently configured as `C:\Python314\python.exe` in `evolver.ps1`)
- `ffprobe` available in `PATH`
- Topaz ffmpeg at `C:\Program Files\Topaz Labs LLC\Topaz Video\ffmpeg.exe`
- Topaz model directory at `C:\ProgramData\Topaz Labs LLC\Topaz Video\models`

## Run manually

From repo root:

```bash
powershell.exe -File run-evolver.ps1
```

Alternative (direct Python command):

```bash
python evolver.py
```

Or through the hidden launcher used by Scheduled Task:

```bash
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File evolver.ps1
```

## One-time correspondence check

If you want to run the same integrity check manually, verify that `1_sorted` and `2_outbox` are in 1-to-1 correspondence (same file count, every sorted file has an outbox file with `_topaz` appended before extension, and every outbox file matches that pattern):

```bash
python check_correspondence.py
```

Output reports any mismatches — orphaned outbox files, orphaned sorted files, count differences, or duplicate outbox basenames. The scheduled flow now runs this same check automatically after the kinda-weird cleanup, after any needed upscale work is finished, and after the duplicate-size scan.

## Logs

- Log file: `evolver.log`
- Each run logs sort, purge, scripts-sync, bookmark-sync, upscale, duplicate-scan, and correspondence summary counts

## Regeneration mode

When `config.REGEN_ENABLED = True`, Evolver writes new outputs to `3_new_outbox` instead of `2_outbox`.

- Correspondence checks treat `2_outbox` and `3_new_outbox` as one combined active output set.
- Existing `2_outbox` files remain valid until their regenerated `3_new_outbox` replacement succeeds.
- After a successful regenerated write, Evolver can delete the matching legacy `2_outbox` file immediately to save disk space.
- When correspondence is clean and the legacy `2_outbox` payload has been fully drained, Evolver can notify you, remove the emptied legacy tree, and rename `3_new_outbox` back to `2_outbox` automatically.
- A completion marker is written to `config.REGEN_COMPLETE_MARKER` so later scheduler ticks stay in normal mode after cutover instead of starting a second regeneration by accident.
- This makes it possible to regenerate the library incrementally while keeping the old outbox available until cutover.

### Regen skip manifest

During regeneration mode, Evolver may write `.regen-skip.txt` in the repo root.

- This is a generated runtime manifest, not source code.
- Each line is a `1_sorted`-relative video path that should be skipped on future regen retries.
- Evolver records an entry when regen work fails but the matching legacy `2_outbox` counterpart still exists, so the same item does not get retried every scheduler run.
- If you want Evolver to retry one of those items, remove that line from `.regen-skip.txt` after dealing with the underlying issue.
- The file is intentionally gitignored.

## Test suite

This repo includes a basic `unittest` suite with no external dependencies.

Run from repo root:

```bash
powershell.exe -File run-tests.ps1
```

Alternative (direct Python command):

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

What is covered:

- Orientation detection logic (`util/ffprobe.py`) via mocked `ffprobe` output
- Sort-stage collision behavior and empty-dir cleanup (`tasks/sort.py`)
- Kinda-weird cleanup and missing-source popup behavior (`tasks/purge_weird.py`)
- Duplicate-size scan for likely same-content source videos (`check_duplicate_sizes.py`)
- Funscript alignment so `videos/scripts/scripts` mirrors `videos/videos` when basename matches are unique within the same `AI` or `non_AI` lane, plus variant-copy support for processed/original counterparts and AI-video duplication into `actually_AI_but_funscripted` (`tasks/scripts_sync.py`)
- Correspondence rules for `<sorted_stem>_topaz<ext>` matching (`check_correspondence.py`)
- Scheduler flow behavior, including always-running purge and pending-work-based Stage 3 decisions (`evolver.py`)
- Interactive popup vs Session-0 `msg.exe` fallback behavior (`util/windows_alert.py`)
- Already-processed detection (`tasks/upscale.py`)

## Notes

- Stage 2 (purge_weird) always runs, regardless of Stage 1 activity.
- Stage 3 always runs after purge. It first moves a script when its basename matches exactly one video in the same `AI` or `non_AI` lane within `videos/videos`, then fills in missing counterpart funscripts for matching processed/original video variants when it can do so unambiguously, then mirrors any funscripted AI videos into `videos/videos/2D/non_AI/actually_AI_but_funscripted`.
- Stage 4 always runs after scripts sync. It reads `fun_time/favs.csv`, resolves the Chrome profile named `Blair` from Chrome `Local State`, and rewrites the `Fun Time Favs` folder on that profile's bookmarks bar from the CSV's `web_url` values.
- Stage 5 runs whenever pending work exists, even if nothing new arrived in `0_inbox` during that scheduler tick.
- Stage 5 is conservative by default: it processes at most `config.UPSCALE_BATCH_LIMIT` videos per run.
- If CPU usage is already above `config.CPU_BUSY_SKIP_THRESHOLD_PCT`, Evolver skips Stage 5 for that scheduler tick instead of competing with other work.
- If free disk space drops below `config.LOW_DISK_WARNING_GB`, Evolver stops Stage 5 early and warns instead of continuing toward a full disk.
- Stage 6 always runs before the final correspondence check and flags likely duplicates in `1_sorted` by exact filesize.
- Stage 7 always runs as the final integrity check, and any mismatch popup points you to `evolver.log` for the full details.
- In interactive runs, errors use a normal Windows message box. In the scheduled S4U task, errors are delivered via `msg.exe` to the active logged-in user.
- Existing output checks prevent duplicate processing.
- Scheduled Task currently points to `evolver.ps1`; updating launcher logic updates scheduled behavior without task re-install.
