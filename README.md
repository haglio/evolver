# Evolver

Evolver is a Windows-scheduled video pipeline that runs every 15 minutes and:

1. Sorts videos from `0_inbox/<source>/` into `1_sorted/<source>/<orientation>/`
2. Purges `2_outbox/kinda_weird/` — deletes every file there and its corresponding source from `1_sorted/`. A Windows error dialog pops up if any source file cannot be found.
3. Upscales/interpolates sorted videos into `2_outbox/upscaled_by_orientation/<orientation>/<source>/` using Topaz Video AI ffmpeg
4. Runs a final 1-to-1 correspondence check between `1_sorted` and `2_outbox`, where each sorted file must have an outbox counterpart named `<sorted_stem>_topaz<ext>`, with a Windows error dialog if mismatches remain

`<source>` is discovered dynamically from directory names. Any new subdirectory under `0_inbox` is treated as a source automatically, and matching output directories are created on demand.

## Current architecture

- Scheduler: Windows Task Scheduler task `evolver` (15-minute trigger)
- Launcher: `evolver.ps1` (hidden, non-interactive)
- Pipeline entry point: `evolver.py`
- Modules:
  - `config.py` - paths and settings
  - `tasks/sort.py` - Stage 1 inbox sorting
  - `tasks/purge_weird.py` - Stage 2 kinda_weird cleanup
  - `tasks/upscale.py` - Stage 3 Topaz processing
  - `check_correspondence.py` - Stage 4 integrity verification and one-time manual check
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

Output reports any mismatches — orphaned outbox files, orphaned sorted files, count differences, or duplicate outbox basenames. The scheduled flow now runs this same check automatically after the kinda-weird cleanup and after any needed upscale work is finished.

## Logs

- Log file: `evolver.log`
- Each run logs Stage 1 and Stage 2 summary counts

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
- Correspondence rules for `<sorted_stem>_topaz<ext>` matching (`check_correspondence.py`)
- Scheduler flow behavior, including always-running purge and skip-upscale-on-no-sort (`evolver.py`)
- Interactive popup vs Session-0 `msg.exe` fallback behavior (`util/windows_alert.py`)
- Already-processed detection (`tasks/upscale.py`)

## Notes

- Stage 2 (purge_weird) always runs, regardless of Stage 1 activity.
- Stage 3 only runs when Stage 1 moved at least one file during that run.
- Stage 4 always runs as the final integrity check, and any mismatch popup points you to `evolver.log` for the full details.
- In interactive runs, errors use a normal Windows message box. In the scheduled S4U task, errors are delivered via `msg.exe` to the active logged-in user.
- Existing output checks prevent duplicate processing.
- Scheduled Task currently points to `evolver.ps1`; updating launcher logic updates scheduled behavior without task re-install.
