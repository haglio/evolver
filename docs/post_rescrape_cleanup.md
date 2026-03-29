# Post-rescrape cleanup

Once all legacy-format prompt JSONs have been migrated, the rescraping
scaffolding in `tasks/prompt_scrape.py` and `config.py` becomes dead code.
This document tells you what to remove and how to verify it is safe to do so.

---

## 1. Verify migration is complete

Scan the metadata directory for any files that are still in the old flat format
(i.e. have a `video_prompt` key instead of a `video` key):

```bash
python3 - <<'EOF'
import json, pathlib, config
legacy = [
    p for p in pathlib.Path(config.METADATA_DIR).rglob("*.json")
    if "video" not in json.loads(p.read_text(encoding="utf-8"))
]
print(f"{len(legacy)} legacy file(s) remaining")
for p in legacy:
    print(" ", p)
EOF
```

If the output is `0 legacy file(s) remaining`, proceed. Otherwise stop —
migration is not done yet.

---

## 2. Deletions

### `config.py`
Remove the `RESCRAPE_BATCH_LIMIT` line entirely:
```python
RESCRAPE_BATCH_LIMIT = 50   # DELETE THIS LINE
```

### `tasks/prompt_scrape.py`

**`PromptScrapeResult` dataclass** — remove two fields:
```python
rescraped: int = 0       # DELETE
skipped_legacy: int = 0  # DELETE
```

**`_is_legacy_format()` function** — delete entirely:
```python
def _is_legacy_format(json_path: Path) -> bool:   # DELETE ENTIRE FUNCTION
    ...
```

**`run()` — the rescrape branch** — replace this block:
```python
if output_path.exists():
    if not _is_legacy_format(output_path):
        result.skipped_existing += 1
        continue
    if result.rescraped >= config.RESCRAPE_BATCH_LIMIT:
        result.skipped_legacy += 1
        continue
```
with the original simple skip:
```python
if output_path.exists():
    result.skipped_existing += 1
    continue
```

**`run()` — `is_rescrape` branch** — replace this block:
```python
is_rescrape = output_path.exists()
...
if is_rescrape:
    result.rescraped += 1
    log.info("Rescrapped legacy prompts: %s", output_path)
else:
    result.scraped += 1
    log.info("Wrote prompts: %s", output_path)
```
with:
```python
result.scraped += 1
log.info("Wrote metadata: %s", output_path)
```

**`run()` — log summary** — remove `rescraped` and `skipped_legacy` from the
final `log.info` call and its format string.

### `tests/test_prompt_scrape.py`
Delete two test methods in `TestPromptScrape`:
- `test_run_rescraped_legacy_json_within_batch_limit`
- `test_run_skips_legacy_rescrape_when_batch_limit_reached`

---

## 3. Confirm

Run the unit tests. All remaining tests must be green before committing:

```bash
python3 -m unittest tests.test_prompt_scrape -v 2>&1 | tail -5
```

Commit message suggestion:
```
Remove legacy-format rescrape scaffolding

Migration of all flat-format prompt JSONs to the nested {"video":...}
structure is complete. The _is_legacy_format check, RESCRAPE_BATCH_LIMIT
config, rescraped/skipped_legacy counters, and associated tests are
no longer needed.
```
