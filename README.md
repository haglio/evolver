# Evolver

Evolver is a video collection maintenance pipeline that runs as a system tray application and:

1. Sorts videos from `0_inbox/<source>/` into `1_sorted/<source>/<orientation>/`
2. Purges `kinda_weird/` outputs from the active outbox set — normally `2_outbox`, and both `2_outbox` plus `3_new_outbox` while regeneration mode is enabled. It also deletes each weird file's corresponding source from `1_sorted/`. A Windows error dialog pops up if any source file cannot be found.
3. Rehomes `.funscript` files under `videos/scripts/scripts` so they mirror the matched video path under `videos/videos`. A script only moves when there is exactly one basename match in the same library lane; scripts under `2D/AI` only consider `2D/AI` videos, and scripts under `2D/non_AI` only consider `2D/non_AI` videos. Unmatched or ambiguous names are logged and left alone. After that, Evolver also copies missing funscripts across matching processed/original video variants, including `1_sorted` <-> `2_outbox` / `3_new_outbox` `_topaz` pairs and matching `processed` <-> non-processed variants within the same source bucket.
4. Prunes stale rows from `fun_time/favs.csv` when the `local_file` or `file` column points at a missing local file, while treating a `2_outbox` favorite as still valid if the matching file currently lives in `3_new_outbox` during regeneration. The CSV itself always keeps `2_outbox` paths, then the remaining `web_url` values are synced into a `Fun Time Favs` folder on the Chrome bookmarks bar for the Chrome profile whose visible name is `Blair`.
5. Scrapes prompt metadata for AI videos in `1_sorted` into `videos/metadata`, mirroring the active outbox tree. The scan is idempotent — videos that already have a metadata JSON are skipped, and a video whose scrape fails is marked so it is not retried every run. Currently supports Provider prompt extraction with the video prompt plus optional source-image prompt keys.
6. Upscales/interpolates sorted videos using Topaz Video AI ffmpeg. Work is now capped per scheduler run, newly sorted inbox files are processed first, and any remaining batch slots can be used for regeneration backlog.
7. Gradually upscales the `2D/non_AI` library too, with the recipe its already-processed clips carry in their `videoai` tags (see "Non-AI library upscaling" below). Off by default — enabled per-session from the tray menu; at most one detached encode runs at a time, and one only starts when the AI queue is drained.
8. Scans `1_sorted` for likely accidental duplicates: video files with the same exact filesize but different filenames, with a Windows error dialog if any are found
9. Runs a final 1-to-1 correspondence check between `1_sorted` and the active outbox set, where each sorted file must have an outbox counterpart named `<sorted_stem>_topaz<ext>`, with a Windows error dialog if mismatches remain

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
  - `tasks/nonai_upscale.py` - the non-AI library's detached Topaz encodes, one at a time
  - `check_duplicate_sizes.py` - Stage 6 duplicate-size scan for likely source duplicates
  - `check_correspondence.py` - Stage 7 integrity verification and one-time manual check
  - `util/ffprobe.py` - orientation probing
  - `util/media_files.py` - shared helpers for finalized-vs-partial video detection and stale partial cleanup
  - `util/sidecar.py` - where a video's metadata JSON lives, and what the upscale stage names its output
  - `util/topaz.py` - the Topaz ffmpeg invocation both upscale stages share
  - `util/variants.py` - the `_apo8`/`_iris2`-style suffixes that pair originals with processed variants
  - `util/processes.py` - liveness, identity, and termination of detached encodes
  - `backfill_app.py` - voice-driven metadata backfill tool (see below), launched from the tray
  - `backfill/vocabulary.py` - the spoken phrases, and the `video.action` each one records
  - `backfill/queue.py` - the clips still missing an action, shuffled
  - `backfill/decisions.py` - writing a clip's action or discarding it as weird, and taking either back
  - `backfill/session.py` - what a heard phrase does to the queue, and the history "undo" walks back through
  - `backfill/work.py` - the single thread the file work runs on, in the order it was spoken
  - `backfill/voice.py` - offline vosk recognition over the tool's grammar
  - `backfill/window.py` - the looping player, the remaining count, and the last decision
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

Say an act, optionally prefixed with a camera word — `side`, or `POV` said as its three letters ("pee oh vee"):

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

So "side gamma" records `Side Gamma`, and "P-O-V delta" records `Pov Delta` — matching the `Pov Epsilon` form Provider already uses, so one Fun Time filter query reaches both. The recognizer listens for the initialism spelled out (`p o v ...`), because the vosk lexicon prices each letter as its name; it also accepts a one-word "pov", whichever way you happen to say it.

Three more phrases:

- `skip` — not now; the clip goes to the back of the queue and comes round again
- `weird` / `trash` — move the clip to `kinda_weird/`, exactly as Fun Time's "mark as weird" does. No metadata is written; Stage 2 later deletes it along with its `1_sorted` source
- `undo` — take the last decision back, and keep saying it to walk back through the whole run

Undo restores the clip to the screen and reverses what the decision did on disk: a sidecar it wrote is deleted (or, if the clip arrived carrying prompts, only the act is removed), and a clip sent to `kinda_weird/` is reclaimed from where it landed. Undoing every decision rewinds the queue to the order it had. It works after the last clip too, so a mislabelled final clip is still recoverable.

Two lines sit beneath the video: what is on screen now and how many clips are left, and what your last phrase did — naming its own clip, which by then is not the one you are watching. `Esc` closes the window; whatever you have labelled is already on disk, and reopening picks up where you left off.

Acts are voiced in plain-English words because the vosk lexicon has none of the compounds — the same trick Fun Time uses. Audio is muted while you label, since the microphone is open the whole time. The window runs as its own process, so it can never take the tray down with it. Set `config.VOICE_DEVICE_INDEX` if the system default input is not the microphone you speak into (`python -m sounddevice` lists them).

## Non-AI library upscaling

The `2D/non_AI` buckets (`winston`, `other`, …) hold full-length real-footage scenes that were being enhanced by hand in the Topaz GUI. Evolver now works through that backlog on its own, using the recipe the already-processed clips record in their `videoai` metadata tags: **apo-8** 60 fps interpolation, then an **iris-2** upscale in auto mode with recover-original-detail at 100, aimed at a 4K frame (Topaz caps small sources at the model's 4x). Real videos keep their soundtrack (re-encoded to AAC), unlike the silent AI clips.

It follows the bucket conventions already in use:

- Candidates come from the triage folders whose names start with `0` or `1` — direct children only, since a nested folder like `1_originals_needing_trimming` stages manual pre-work that should happen first.
- The output lands in the bucket's `3*/processed/` folder as `<stem>_apo8_iris2.mp4`, and the original then moves to the bucket's `2*` ("do not need work") folder.
- A video is skipped when any processed variant of it already exists in the bucket (`_iris2`, `_apo8_prob4`, and friends — see `util/variants.py`), or when it already carries a `videoai` tag itself.
- `actually_AI_but_funscripted/` is left alone; its contents are AI-pipeline outputs.

**Order**: an explicit `1 could use work` flag goes first; then Fun Time watch score, descending — read straight from `fun_time/state/watch_stats.json` with the same `completions + 3×locks − skips` arithmetic its playlist breeding uses, so once Fun Time starts tracking primary (Nau/Hybrid) plays, the most-watched videos move to the front on their own; funscript ownership breaks ties among the unwatched (a fair proxy, since Nau drives the OSR2 with them); then everything else alphabetically.

**Off by default — flip it on when stepping away.** One of these encodes monopolizes the GPU for hours and can make the desktop crawl, so the stage starts nothing until **Upscale Non-AI When Idle** is checked in the tray menu. The toggle applies on the next scheduler tick, no restart needed. Unchecking it mid-encode kills the in-flight ffmpeg and the video keeps its place in the queue — no retry penalty; an encode that already finished is still promoted. Headless CLI runs (`python evolver.py`) have no toggle and neither start nor stop encodes; they only promote finished ones.

**Gradually** means: one video at a time. These encodes take hours, and the tray watchdog kills a pipeline run at eleven minutes, so the stage never waits on ffmpeg. It launches a single detached, below-normal-priority Topaz process and returns; each later scheduler tick checks on it. A finished encode (output duration ≥ 98% of the source's) is promoted and its original retired; an interrupted or failed one is retried once and then parked in `.nonai-upscale-skip.txt` (repo root, gitignored, one `path<TAB>reason` per line — delete a line to retry it). An encode still running after 24 hours is killed, but only after confirming the pid still belongs to Topaz ffmpeg. A new encode starts only when the toggle is on, the AI upscale queue is drained, CPU is below the busy threshold, and free disk is above the safety floor.

**Watching it**: every tick appends one line to `evolver.log` — `Non-AI upscale: started=... in_flight=... promoted=... stopped=... failed=... pending=...` — so a `grep "Non-AI"` over the log is the quickest status. While an encode runs, `in_flight` carries its progress, e.g. `in_flight=other/0 unsorted/clip.mp4 (37% encoded)`, measured by probing the duration written to the growing partial so far (the first minute or two may show no percentage while the file's header lands). What's encoding right now (source, output, pid, start time) sits in `nonai_upscale_job.json`, and the encode's own stderr streams to `nonai_upscale_ffmpeg.log`. The same per-tick summary — including `in_flight_percent` — lands in each run's record, visible in the main window's run history under the **Upscale non-AI** stage row.

In-flight state lives in `nonai_upscale_job.json` (plus `nonai_upscale_attempts.json` for the retry counter) — all in the repo root and gitignored. Quitting the tray app does not kill the encode; the next session picks it back up from the state file.

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
- Non-AI candidate discovery, priority order, and the detached-encode lifecycle: launch, in-flight, promote, retry, skip-manifest, and stuck-job kill (`tasks/nonai_upscale.py`)

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
- Stage 7 (non-AI upscale) always runs so it can check on its detached encode, but only launches a new one when the AI queue is drained and the box is otherwise quiet.
- Stage 8 always runs before the final correspondence check and flags likely duplicates in `1_sorted` by exact filesize.
- Stage 9 always runs as the final integrity check, and any mismatch popup points you to `evolver.log` for the full details.
- Errors are shown via Windows message box.
- Existing output checks prevent duplicate processing.
