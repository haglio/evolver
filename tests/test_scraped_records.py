from __future__ import annotations

from pathlib import Path

from util import scraped_records
from util.scraped_records import ScrapedRecords


def test_a_record_staged_for_an_upscale_is_read_back_until_it_is_dropped(tmp_path):
    staged = ScrapedRecords(tmp_path / "state" / "scraped.json")
    upscale = tmp_path / "kino" / "scene one_topaz.mp4"

    staged.stage(upscale, {"video": {"prompt": "made up"}})

    assert staged.staged(upscale) == {"video": {"prompt": "made up"}}
    assert staged.waiting() == [(upscale, {"video": {"prompt": "made up"}})]
    staged.drop(upscale)
    assert (staged.staged(upscale), staged.waiting()) == (None, [])


def test_an_upscale_is_one_entry_however_its_path_is_spelled(tmp_path):
    staged = ScrapedRecords(tmp_path / "scraped.json")

    staged.stage(tmp_path / "Scene One_topaz.mp4", {"video": {"seed": "1"}})

    assert staged.staged(Path(str(tmp_path / "scene one_topaz.mp4").upper())) == {
        "video": {"seed": "1"}}


def test_a_failed_scrape_is_remembered_beside_the_records_and_never_read_as_one(tmp_path):
    staged = ScrapedRecords(tmp_path / "scraped.json")
    upscale = tmp_path / "scene two_topaz.mp4"

    staged.mark_failed(upscale, tmp_path / "scene two.mp4", RuntimeError("no prompt on the page"))

    assert staged.failed(upscale)
    assert not staged.failed(tmp_path / "scene three_topaz.mp4")
    assert (staged.staged(upscale), staged.waiting()) == (None, [])


def test_nothing_staged_reads_as_nothing_waiting(tmp_path):
    assert ScrapedRecords(tmp_path / "never written.json").waiting() == []


def test_asked_about_many_upscales_it_reads_its_file_once_and_again_only_after_it_writes(
        tmp_path, monkeypatch):
    reads = []
    real_read = scraped_records.read_json_or_empty
    monkeypatch.setattr(scraped_records, "read_json_or_empty",
                        lambda path: reads.append(path) or real_read(path))
    records = scraped_records.ScrapedRecords(tmp_path / "scraped.json")
    upscales = [tmp_path / f"video {number}_topaz.mp4" for number in range(5)]

    for upscale in upscales:
        assert records.staged(upscale) is None
        assert not records.failed(upscale)
    records.stage(upscales[0], {"prompt": "made up"})

    assert records.staged(upscales[0]) == {"prompt": "made up"}
    assert len(reads) == 1
