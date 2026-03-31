# Evolver

Evolver is a video collection maintenance pipeline that runs as a system tray application and:

1. Sorts videos from `0_inbox/<source>/` into `1_sorted/<source>/<orientation>/`
2. Purges `kinda_weird/` outputs from the active outbox set — normally `2_outbox`, and both `2_outbox` plus `3_new_outbox` while regeneration mode is enabled. It also deletes each weird file's corresponding source from `1_sorted/`. A Windows error dialog pops up if any source file cannot be found.
3. Rehomes `.funscript` files under `videos/scripts/scripts` so they mirror the matched video path under `videos/videos`. A script only moves when there is exactly one basename match in the same library lane; scripts under `2D/AI` only consider `2D/AI` videos, and scripts under `2D/non_AI` only consider `2D/non_AI` videos. Unmatched or ambiguous names are logged and left alone. After that, Evolver also copies missing funscripts across matching processed/original video variants, including `1_sorted` <-> `2_outbox` / `3_new_outbox` `_topaz` pairs and matching `processed` <-> non-processed variants within the same source bucket.
4. Prunes stale rows from `fun_time/favs.csv` when the `local_file` or `file` column points at a missing local file, while treating a `2_outbox` favorite as still valid if the matching file currently lives in `3_new_outbox` during regeneration. The CSV itself always keeps `2_outbox` paths, then the remaining `web_url` values are synced into a `Fun Time Favs` folder on the Chrome bookmarks bar for the Chrome profile whose visible name is `Blair`.
5. Scrapes prompt metadata for AI videos into `videos/prompts`, mirroring the active outbox tree. Each JSON file is named after its video and currently supports Provider prompt extraction with `video_prompt` plus optional source-image prompt keys.
6. Upscales/interpolates sorted videos using Topaz Video AI ffmpeg. Work is now capped per scheduler run, newly sorted inbox files are processed first, and any remaining batch slots can be used for regeneration backlog.
7. Scans `1_sorted` for likely accidental duplicates: video files with the same exact filesize but different filenames, with a Windows error dialog if any are found
8. Runs a final 1-to-1 correspondence check between `1_sorted` and the active outbox set, where each sorted file must have an outbox counterpart named `<sorted_stem>_topaz<ext>`, with a Windows error dialog if mismatches remain

`<source>` is discovered dynamically from directory names. Any new subdirectory under `0_inbox` is treated as a source automatically, and matching output directories are created on demand.

## Current architecture

- **Tray app**: `pythonw.exe tray_app.py` — system tray icon with GUI, configurable timer (default 10 min), manual run trigger, run history, and live progress bars
- **CLI mode**: `python evolver.py` — headless single run, returns exit code
- Pipeline entry point: `evolver.py`
- Modules:
  - `config.py` - paths and settings
  - `tasks/sort.py` - Stage 1 inbox sorting
  - `tasks/purge_weird.py` - Stage 2 kinda_weird cleanup
  - `tasks/scripts_sync.py` - Stage 3 funscript/video tree alignment and processed/original variant copying
  - `tasks/bookmarks_sync.py` - Stage 3.5 favorites -> Chrome bookmarks sync
  - `tasks/prompt_scrape.py` - Stage 4 prompt scraping into mirrored JSON files
  - `tasks/upscale.py` - Stage 5 Topaz processing
  - `check_duplicate_sizes.py` - Stage 6 duplicate-size scan for likely source duplicates
  - `check_correspondence.py` - Stage 7 integrity verification and one-time manual check
  - `util/ffprobe.py` - orientation probing
  - `util/media_files.py` - shared helpers for finalized-vs-partial video detection and stale partial cleanup
  - `gui/app.py` - tray application wiring and single-instance guard
  - `gui/tray.py` - system tray icon and context menu
  - `gui/main_window.py` - run history list and detail/progress panel
  - `gui/progress.py` - live per-stage progress widget
  - `gui/worker.py` - background QThread pipeline runner
  - `gui/scheduler.py` - timer-based scheduling with run-guard
  - `gui/run_record.py` - JSON run record persistence
  - `gui/settings.py` - settings dataclass and persistence
  - `gui/startup.py` - Windows Startup folder shortcut management

## Requirements

- Windows
- Python 3.14+
- `ffprobe` available in `PATH`
- Topaz ffmpeg at `C:\Program Files\Topaz Labs LLC\Topaz Video\ffmpeg.exe`
- Topaz model directory at `C:\ProgramData\Topaz Labs LLC\Topaz Video\models`
- PyQt6 (`pip install PyQt6`)

## Run as tray app (recommended)

```bash
pythonw.exe tray_app.py
```

This starts a system tray icon. Right-click for the context menu (Run Now, Pause/Resume, Settings, Quit) or double-click to open the main window with run history and live progress. Configure the run interval and Windows startup registration from Settings.

Run history is stored as JSON files in `runs/` (gitignored). Settings are persisted to `gui_settings.json` (gitignored).

## Run manually (CLI)

From repo root:

```bash
powershell.exe -File evolver.ps1
```

Alternative (direct Python command):

```bash
python evolver.py
```

## One-time correspondence check

If you want to run the same integrity check manually, verify that `1_sorted` and `2_outbox` are in 1-to-1 correspondence (same file count, every sorted file has an outbox file with `_topaz` appended before extension, and every outbox file matches that pattern):

```bash
python check_correspondence.py
```

Output reports any mismatches — orphaned outbox files, orphaned sorted files, count differences, or duplicate outbox basenames. The scheduled flow now runs this same check automatically after the kinda-weird cleanup, after any needed upscale work is finished, and after the duplicate-size scan.

## Logs

- Log file: `evolver.log`
- Each run logs sort, purge, scripts-sync, bookmark-sync, prompt-scrape, upscale, duplicate-scan, and correspondence summary counts

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
- Funscript alignment so `videos/scripts/scripts` mirrors `videos/videos` when basename matches are unique within the same `AI` or `non_AI` lane, plus variant-copy support for processed/original counterparts (`tasks/scripts_sync.py`)
- Correspondence rules for `<sorted_stem>_topaz<ext>` matching (`check_correspondence.py`)
- Scheduler flow behavior, including always-running purge and pending-work-based Stage 3 decisions (`evolver.py`)
- Already-processed detection (`tasks/upscale.py`)
- Partial-file handling across upscale cleanup and downstream scanners (`tasks/upscale.py`, `check_correspondence.py`, `tasks/prompt_scrape.py`, `tasks/sort.py`)

## Output temp-file contract

Stage 5 writes Topaz output to a temporary filename before promoting it to the final `_topaz` path.

- Temp files use the pattern `*.partial.<uuid>.mp4`
- Temp files are not considered valid library videos
- Shared filtering and cleanup lives in `util/media_files.py`
- On each Stage 5 run, stale partial outputs under the active upscale target are deleted before new work starts

For a concise maintainer-oriented summary, see `docs/maintenance_notes.md`.

## Notes

- Stage 2 (purge_weird) always runs, regardless of Stage 1 activity.
- Stage 3 always runs after purge. It first moves a script when its basename matches exactly one video in the same `AI` or `non_AI` lane within `videos/videos`, then fills in missing counterpart funscripts for matching processed/original video variants when it can do so unambiguously.
- Stage 4 always runs after scripts sync. It first normalizes any accidental `3_new_outbox` references in `favs.csv` back to `2_outbox`, then removes rows whose local favorite file no longer exists in either `2_outbox` or `3_new_outbox`, and finally resolves the Chrome profile named `Blair` from Chrome `Local State` and rewrites the `Fun Time Favs` folder on that profile's bookmarks bar from the remaining CSV `web_url` values.
- Stage 5 writes prompt JSON files under `videos/prompts/<2_outbox or 3_new_outbox>/.../<video-name>.json`, skipping files that already have JSON output. The current scraper only extracts Provider prompts.
- Stage 6 runs whenever pending work exists, even if nothing new arrived in `0_inbox` during that scheduler tick.
- Stage 6 is conservative by default: it processes at most `config.UPSCALE_BATCH_LIMIT` videos per run.
- If CPU usage is already above `config.CPU_BUSY_SKIP_THRESHOLD_PCT`, Evolver skips Stage 6 for that scheduler tick instead of competing with other work.
- If free disk space drops below `config.LOW_DISK_WARNING_GB`, Evolver stops Stage 6 early and warns instead of continuing toward a full disk.
- Stage 7 always runs before the final correspondence check and flags likely duplicates in `1_sorted` by exact filesize.
- Stage 8 always runs as the final integrity check, and any mismatch popup points you to `evolver.log` for the full details.
- Errors are shown via Windows message box.
- Existing output checks prevent duplicate processing.
