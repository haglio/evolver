from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

import config
from tasks import origenerator_commands
from util import origenerator_gallery

DOWNTIME = [".venv/Scripts/python.exe", "-m", "origenerator.downtime"]
GALLERY_ENTRIES = [".venv/Scripts/python.exe", "-m", "origenerator.outside_video_entries"]


def _checkout(tmp_path, **published):
    (tmp_path / origenerator_gallery.PUBLISHED).write_text(json.dumps(published), encoding="utf-8")
    return tmp_path


@dataclass(frozen=True)
class _Answered:
    stdout: str


def _answering(stdout: str, ran: list):
    def runner(args, **options):
        ran.append((args, options))
        return _Answered(stdout)
    return runner


def _never_answers(args, **options):
    raise subprocess.TimeoutExpired(args, options["timeout"])


def test_origenerators_published_command_runs_from_its_checkout_and_its_answer_is_passed_on(
        tmp_path):
    checkout = _checkout(tmp_path, downtime_command=DOWNTIME)
    ran = []
    said = json.dumps({"did": "nothing: a fix is training", "holds_the_graphics_card": True})

    result = origenerator_commands.run_downtime(
        checkout, runner=_answering(f"warming up\n{said}\n", ran))

    assert (result.did, result.holds_the_graphics_card, result.failed) == (
        "nothing: a fix is training", True, False)
    ((args, options),) = ran
    assert args == [str(checkout / ".venv/Scripts/python.exe"), "-m", "origenerator.downtime"]
    assert options["cwd"] == str(checkout)
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_an_origenerator_that_names_no_such_work_is_left_alone(tmp_path):
    ran = []

    result = origenerator_commands.run_downtime(_checkout(tmp_path), runner=_answering("", ran))

    assert (ran, result.failed, result.holds_the_graphics_card) == ([], False, False)


def test_an_answer_that_cannot_be_read_fails_the_stage_rather_than_passing_in_silence(tmp_path):
    checkout = _checkout(tmp_path, downtime_command=["python.exe", "-m", "origenerator.downtime"])

    result = origenerator_commands.run_downtime(
        checkout, runner=_answering("Traceback (most recent", []))

    assert (result.failed, result.holds_the_graphics_card) == (True, False)


def test_origenerators_own_command_writes_its_gallerys_entries_from_its_checkout_unseen(
        tmp_path, caplog):
    checkout, ran = _checkout(tmp_path, outside_video_entries_command=GALLERY_ENTRIES), []

    with caplog.at_level(logging.INFO):
        written = origenerator_commands.write_gallery_entries(
            checkout, runner=_answering('starting\n{"brought_in": 2}\n', ran))

    assert written is True
    ((args, options),) = ran
    assert args == [str(checkout / ".venv/Scripts/python.exe"), "-m",
                    "origenerator.outside_video_entries"]
    assert options["cwd"] == str(checkout)
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert "took in 2 video(s)" in caplog.text


def test_an_origenerator_from_before_it_took_entries_this_way_is_left_to_its_own_look(tmp_path):
    ran = []

    written = origenerator_commands.write_gallery_entries(
        _checkout(tmp_path), runner=_answering("", ran))

    assert (written, ran) == (True, [])


def test_a_gallery_whose_answer_cannot_be_read_is_reported_rather_than_passed_in_silence(
        tmp_path, caplog):
    checkout = _checkout(tmp_path, outside_video_entries_command=GALLERY_ENTRIES)

    with caplog.at_level(logging.WARNING):
        written = origenerator_commands.write_gallery_entries(
            checkout, runner=_answering("Traceback (most recent", []))

    assert written is False
    assert "could not be told" in caplog.text


def test_a_gallery_command_that_never_comes_back_is_given_up_on(tmp_path):
    checkout = _checkout(tmp_path, outside_video_entries_command=GALLERY_ENTRIES)

    assert origenerator_commands.write_gallery_entries(checkout, runner=_never_answers) is False


def test_the_gallery_command_is_given_less_time_than_a_run_keeps_spare_after_its_upscales(
        tmp_path):
    checkout, ran = _checkout(tmp_path, outside_video_entries_command=GALLERY_ENTRIES), []

    origenerator_commands.write_gallery_entries(
        checkout, runner=_answering('{"brought_in": 0}', ran))

    ((_args, options),) = ran
    spare = config.PIPELINE_WALL_TIMEOUT_SECONDS - config.UPSCALE_RUN_BUDGET_SECONDS
    assert 0 < options["timeout"] < spare



RECORDS = [".venv/Scripts/python.exe", "-m", "origenerator.ai_video_records"]


def _handing_over(stdout: str, handed: list):
    def runner(args, **options):
        files = [Path(args[i + 1]) for i, arg in enumerate(args)
                 if arg in ("--record", "--totals", "--provenance")]
        handed.append((args, options, [json.loads(file.read_text(encoding="utf-8"))
                                       for file in files]))
        return _Answered(stdout)
    return runner


def test_a_sites_record_of_a_video_is_handed_to_the_gallery_from_origenerators_checkout(
        tmp_path):
    checkout, handed = _checkout(tmp_path, records_command=RECORDS), []
    video = tmp_path / "kino" / "scene one_topaz.mp4"
    gallery = origenerator_commands.GalleryRecords(
        checkout, runner=_handing_over('{"done": 1, "no_row": 0}', handed))

    answer = gallery.record(video, {"video": {"prompt": "made up"}})

    assert answer == origenerator_commands.Handed(done=1, no_row=0)
    ((args, options, given),) = handed
    assert args[:6] == [str(checkout / ".venv/Scripts/python.exe"), "-m",
                        "origenerator.ai_video_records", "record", "--video", str(video)]
    assert args[6] == "--record"
    assert given == [{"video": {"prompt": "made up"}}]
    assert options["cwd"] == str(checkout)
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_the_file_handed_over_is_gone_once_the_gallery_has_answered(tmp_path):
    handed = []
    gallery = origenerator_commands.GalleryRecords(
        _checkout(tmp_path, records_command=RECORDS),
        runner=_handing_over('{"done": 1, "no_row": 0}', handed))

    gallery.upscaled(tmp_path / "a.mp4", {"app": "evolver"})

    ((args, _options, _given),) = handed
    assert not Path(args[args.index("--provenance") + 1]).exists()


def test_every_verb_names_its_video_and_hands_over_what_it_was_given(tmp_path):
    handed = []
    video = tmp_path / "a.mp4"
    gallery = origenerator_commands.GalleryRecords(
        _checkout(tmp_path, records_command=RECORDS),
        runner=_handing_over('{"done": 2, "no_row": 1}', handed))

    gallery.watched({video: {"completions": 2, "skips": 0, "locks": 1}})
    gallery.favorite(video, True)
    gallery.favorite(video, False)
    gallery.upscaled(video, {"app": "evolver"})

    assert [(args[3:], given) for args, _options, given in handed] == [
        (["watched", "--totals", handed[0][0][5]],
         [{str(video): {"completions": 2, "skips": 0, "locks": 1}}]),
        (["favorite", "--video", str(video), "--on"], []),
        (["favorite", "--video", str(video), "--off"], []),
        (["upscaled", "--video", str(video), "--provenance", handed[3][0][7]],
         [{"app": "evolver"}]),
    ]


def test_an_origenerator_from_before_it_took_records_is_asked_nothing(tmp_path):
    ran = []

    answer = origenerator_commands.GalleryRecords(
        _checkout(tmp_path), runner=_answering("", ran)).favorite(tmp_path / "a.mp4", True)

    assert (answer, ran) == (None, [])


def test_a_gallery_that_cannot_answer_about_a_record_is_reported_rather_than_passed_in_silence(
        tmp_path, caplog):
    gallery = origenerator_commands.GalleryRecords(
        _checkout(tmp_path, records_command=RECORDS), runner=_never_answers)

    with caplog.at_level(logging.WARNING):
        answer = gallery.favorite(tmp_path / "a.mp4", True)

    assert answer is None
    assert "could not be handed" in caplog.text


def test_a_gallery_left_to_its_usual_runner_is_never_the_real_one_in_a_test(tmp_path):
    gallery = origenerator_commands.GalleryRecords(_checkout(tmp_path, records_command=RECORDS))

    with pytest.raises(AssertionError, match="real gallery"):
        gallery.favorite(tmp_path / "a.mp4", True)


def test_videos_the_gallery_has_no_row_for_are_counted_in_the_log(tmp_path, caplog):
    gallery = origenerator_commands.GalleryRecords(
        _checkout(tmp_path, records_command=RECORDS),
        runner=_answering('{"done": 1, "no_row": 2}', []))

    with caplog.at_level(logging.INFO):
        gallery.watched({tmp_path / "a.mp4": {}, tmp_path / "b.mp4": {}, tmp_path / "c.mp4": {}})

    assert "no row for 2 of the videos" in caplog.text
