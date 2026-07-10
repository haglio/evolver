# Evolver

Evolver is a video collection maintenance pipeline that runs as a system tray application and:

1. Sorts videos from `0_inbox/<source>/` into `1_sorted/<source>/<orientation>/`
2. Purges `kinda_weird/` outputs from the active outbox set — normally `2_outbox`, and both `2_outbox` plus `3_new_outbox` while regeneration mode is enabled. It also deletes each weird file's corresponding source from `1_sorted/`. A Windows error dialog pops up if any source file cannot be found.
3. Rehomes `.funscript` files under `videos/scripts/scripts` so they mirror the matched video path under `videos/videos`. A script only moves when there is exactly one basename match in the same library lane; scripts under `2D/AI` only consider `2D/AI` videos, and scripts under `2D/non_AI` only consider `2D/non_AI` videos. Unmatched or ambiguous names are logged and left alone. After that, Evolver also copies missing funscripts across matching processed/original video variants, including `1_sorted` <-> `2_outbox` / `3_new_outbox` `_topaz` pairs and matching `processed` <-> non-processed variants within the same source bucket.
4. Prunes stale rows from `fun_time/favs.csv` when the `local_file` or `file` column points at a missing local file, while treating a `2_outbox` favorite as still valid if the matching file currently lives in `3_new_outbox` during regeneration. The CSV itself always keeps `2_outbox` paths, then the remaining `web_url` values are synced into a `Fun Time Favs` folder on the Chrome bookmarks bar for the Chrome profile whose visible name is `Blair`.
5. Scrapes prompt metadata for AI videos in `1_sorted` into `videos/metadata`, mirroring the active outbox tree. The scan is idempotent — videos that already have a metadata JSON are skipped, and a video whose scrape fails is marked so it is not retried every run. Currently supports Provider prompt extraction with the video prompt plus optional source-image prompt keys.
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
  - `util/sidecar.py` - where a video's metadata JSON lives, and what the upscale stage names its output
  - `backfill_app.py` - voice-driven metadata backfill tool (see below), launched from the tray
  - `backfill/vocabulary.py` - the spoken phrases, and the `video.action` each one records
  - `backfill/queue.py` - the clips still missing an action, shuffled
  - `backfill/decisions.py` - writing a clip's action, or discarding it as weird
  - `backfill/session.py` - what a heard phrase does to the queue
  - `backfill/voice.py` - offline vosk recognition over the tool's grammar
  - `backfill/window.py` - the looping player and its remaining-count status line
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
- `vosk` and `sounddevice`, for the backfill tool's voice commands (`pip install vosk sounddevice`). The speech model is downloaded and cached on first use.

## Run as tray app (recommended)

```bash
pythonw.exe tray_app.py
```

This starts a system tray icon. Right-click for the context menu (Run Now, Pause/Resume, Settings, Stats, Backfill Metadata, Quit) or double-click to open the main window with run history and live progress. Configure the run interval and Windows startup registration from Settings.

Run history is stored as JSON files in `runs/` (gitignored). Settings are persisted to `gui_settings.json` (gitignored).

## Metadata backfill tool

Most sources publish nothing about what a clip actually shows. Provider exposes an action on its site and Origenerator has its gallery database, so Stage 5 fills those in on its own; a clip from Provider2, Provider3, Candy, ComfyUI or Provider4 arrives with no `video.action` at all, and Fun Time cannot group or filter it.

**Backfill Metadata...** in the tray menu opens a separate window that plays every such clip — shuffled, looping, muted — until you say what it is. The clip changes the instant you speak, and the sidecar is written behind it.

Say an act, optionally prefixed with a camera word (`side` or `pov`/`point of view`):

| Say | Records |
| --- | --- |
| `alpha form` / `alpha` | `Alpha` |
| `gamma` | `Gamma` |
| `epsilon` | `Epsilon` |
| `zeta` | `Zeta` |
| `beta gamma` | `Beta Gamma` |
| `delta` | `Delta` |
| `delta` | `Delta` |
| `dance` | `Dancing` (no camera word) |
| `other` | `Other` (no camera word) |

So "side gamma" records `Side Gamma`, and "pov delta" records `Pov Delta` — matching the `Pov Epsilon` form Provider already uses, so one Fun Time filter query reaches both.

Two more phrases:

- `skip` — not now; the clip goes to the back of the queue and comes round again
- `weird` / `trash` — move the clip to `kinda_weird/`, exactly as Fun Time's "mark as weird" does. No metadata is written; Stage 2 later deletes it along with its `1_sorted` source

The status line shows how many clips still need an action. `Esc` closes the window; whatever you have labelled is already on disk, and reopening picks up where you left off.

Acts are voiced in plain-English words because the vosk lexicon has none of the compounds — the same trick Fun Time uses. Audio is muted while you label, since the microphone is open the whole time. The window runs as its own process, so it can never take the tray down with it. Set `config.VOICE_DEVICE_INDEX` if the system default input is not the microphone you speak into (`python -m sounddevice` lists them).

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
- Stage 5 scans `1_sorted` and writes prompt JSON files under `videos/metadata/<2_outbox or 3_new_outbox>/.../<video-name>_topaz.json`, skipping any video that already has a JSON. A video whose scrape fails (for example, its source page was deleted) gets a sibling `<video-name>_topaz.json.failed` marker so it is not retried every run; delete the marker to force a retry. The current scraper only extracts Provider prompts.
- Stage 6 runs whenever pending work exists, even if nothing new arrived in `0_inbox` during that scheduler tick.
- Stage 6 is conservative by default: it processes at most `config.UPSCALE_BATCH_LIMIT` videos per run.
- If CPU usage is already above `config.CPU_BUSY_SKIP_THRESHOLD_PCT`, Evolver skips Stage 6 for that scheduler tick instead of competing with other work.
- If free disk space drops below `config.LOW_DISK_WARNING_GB`, Evolver stops Stage 6 early and warns instead of continuing toward a full disk.
- Stage 7 always runs before the final correspondence check and flags likely duplicates in `1_sorted` by exact filesize.
- Stage 8 always runs as the final integrity check, and any mismatch popup points you to `evolver.log` for the full details.
- Errors are shown via Windows message box.
- Existing output checks prevent duplicate processing.
