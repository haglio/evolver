from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass

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


def test_a_video_origenerator_sent_is_told_to_its_gallery_like_any_other_sites():
    told = []

    for source in ("origenerator", "a-site"):
        origenerator_commands.write_the_gallery_entry_of_a_video_from(
            source, write=lambda source=source: told.append(source))

    assert told == ["origenerator", "a-site"]
