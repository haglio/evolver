# Maintenance Notes

## Finalized vs partial video files

Evolver intentionally writes Topaz output to a temporary filename before promoting it to the final `_topaz` name.

- Temporary outputs use the pattern `*.partial.<uuid>.mp4`.
- These files are considered transient implementation details, not user-facing library entries.
- Stages that scan for videos must ignore partial files.
- Stage 5 (`tasks/upscale.py`) removes any stale partial outputs from the target outbox before starting new work.
- The non-AI stage (`tasks/nonai_upscale.py`) does the same under each bucket's `3*/processed/` folder, sparing only the tmp file its live detached job is still writing.

The shared helpers for this contract live in `util/media_files.py`:

- `is_partial_video_path()`
- `is_finalized_video_file()`
- `iter_finalized_videos()`
- `remove_partial_video_files()`

If a future change adds a new stage that scans video trees, prefer `iter_finalized_videos(...)` instead of open-coding `rglob("*")` plus an extension check.

## Tests that protect this behavior

The current regression coverage for partial-file handling is intentionally spread across multiple stages:

- `tests/test_upscale.py`
  Covers startup cleanup of stale partial outputs.
- `tests/test_correspondence.py`
  Verifies outbox integrity checks ignore partial files.
- `tests/test_prompt_scrape.py`
  Verifies prompt scraping does not emit JSON for partial videos.
- `tests/test_sort.py`
  Verifies inbox scanning ignores partial files.

When modifying temp-file naming, output promotion, or library scans, run:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```
