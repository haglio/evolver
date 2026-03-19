# Evolver

Evolver is a Windows-scheduled video pipeline that runs every 15 minutes and:

1. Sorts videos from `0_inbox/<source>/` into `1_sorted/<source>/<orientation>/`
2. Upscales/interpolates sorted videos into `2_outbox/upscaled_by_orientation/<orientation>/<source>/` using Topaz Video AI ffmpeg

## Current architecture

- Scheduler: Windows Task Scheduler task `evolver` (15-minute trigger)
- Launcher: `evolver.ps1` (hidden, non-interactive)
- Pipeline entry point: `evolver.py`
- Modules:
  - `config.py` - paths and settings
  - `tasks/sort.py` - Stage 1 inbox sorting
  - `tasks/upscale.py` - Stage 2 Topaz processing
  - `util/ffprobe.py` - orientation probing

## Requirements

- Windows
- Python 3.14+ (currently configured as `C:\Python314\python.exe` in `evolver.ps1`)
- `ffprobe` available in `PATH`
- Topaz ffmpeg at `C:\Program Files\Topaz Labs LLC\Topaz Video\ffmpeg.exe`
- Topaz model directory at `C:\ProgramData\Topaz Labs LLC\Topaz Video\models`

## Run manually

From repo root:

```powershell
.\run-evolver.ps1
```

Alternative (direct Python command):

```powershell
python .\evolver.py
```

Or through the hidden launcher used by Scheduled Task:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File .\evolver.ps1
```

## Logs

- Log file: `evolver.log`
- Each run logs Stage 1 and Stage 2 summary counts

## Test suite

This repo includes a basic `unittest` suite with no external dependencies.

Run from repo root:

```powershell
.\run-tests.ps1
```

Alternative (direct Python command):

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

What is covered:

- Orientation detection logic (`util/ffprobe.py`) via mocked `ffprobe` output
- Sort-stage collision behavior and empty-dir cleanup (`tasks/sort.py`)
- Already-processed detection (`tasks/upscale.py`)

## Notes

- Stage 2 only runs when Stage 1 moved at least one file during that run.
- Existing output checks prevent duplicate processing.
- Scheduled Task currently points to `evolver.ps1`; updating launcher logic updates scheduled behavior without task re-install.
