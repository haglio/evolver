# Maintenance Notes

## Finalized vs partial video files

Evolver writes Topaz output to a temporary file beside its final name, and renames it into place only once the encode is whole.

- Temporary outputs are named `<stem>.partial.<uuid>`, with no video extension, so Fun Time, Nau, Genau and anything else that lists videos by extension never takes an unfinished encode for a video. A non-AI encode's file sits in the library for hours, frozen while the user is at the machine, which is exactly when the players are open.
- ffmpeg is told the container with `-f mp4`, since the name gives it nothing to infer one from.
- Stages that scan for videos must ignore partial files. Any name holding `.partial.` is one, whatever it ends in: Origenerator's exports into the inbox still end in `.mp4` while they copy.
- The upscale stage (`tasks/upscale.py`) removes any stale partial outputs from the target outbox before starting new work.
- The non-AI stage (`tasks/nonai_upscale.py`) does the same under each bucket's `3*/processed/` folder, sparing only the tmp file its live detached job is still writing.

The shared helpers for this contract live in `util/media_files.py`:

- `partial_path()` and `partial_stem()`
- `is_partial_path()`
- `is_finalized_video_file()`
- `library_videos()`
- `remove_partial_files()`

If a future change adds a new stage that scans video trees, prefer `library_videos(...)` instead of open-coding `rglob("*")` plus an extension check.

`tasks/stray_files.py` is the one deliberate exception. It exists to look at what those helpers filter *out*, so it walks `rglob("*")` itself, and skips partial files by name: an in-flight write is neither a stray to fix nor news to report.

## Tests that protect this behavior

- `tests/test_media_files.py` covers the name, and the sweep.
- `tests/test_upscale.py` and `tests/test_nonai_upscale.py` cover what each stage writes and what it sweeps.
- `tests/test_stray_files.py`, `tests/test_correspondence.py`, `tests/test_prompt_scrape.py`, `tests/test_lanes.py` and `tests/test_backfill_queue.py` cover scans that must pass partial files by.

When modifying temp-file naming, output promotion, or library scans, run:

```bash
.venv/Scripts/python.exe -m pytest
```
