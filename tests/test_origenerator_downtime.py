from __future__ import annotations

import json
import subprocess
import types

from tasks import origenerator_downtime
from util import origenerator_gallery


def _checkout(tmp_path, **published):
    (tmp_path / origenerator_gallery.PUBLISHED).write_text(json.dumps(published), encoding="utf-8")
    return tmp_path


def _answering(stdout: str, ran: list):
    def runner(args, **options):
        ran.append((args, options))
        return types.SimpleNamespace(stdout=stdout, returncode=0)
    return runner


def test_origenerators_published_command_runs_from_its_checkout_and_its_answer_is_passed_on(
        tmp_path):
    checkout = _checkout(tmp_path, downtime_command=[".venv/Scripts/python.exe", "-m",
                                                     "origenerator.downtime"])
    ran = []
    said = json.dumps({"did": "started training the hands fix", "holds_the_graphics_card": True})

    result = origenerator_downtime.run(checkout, runner=_answering(f"warming up\n{said}\n", ran))

    assert (result.did, result.holds_the_graphics_card, result.failed) == (
        "started training the hands fix", True, False)
    ((args, options),) = ran
    assert args == [str(checkout / ".venv/Scripts/python.exe"), "-m", "origenerator.downtime"]
    assert options["cwd"] == str(checkout)
    assert options["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_an_origenerator_that_names_no_such_work_is_left_alone(tmp_path):
    ran = []

    result = origenerator_downtime.run(_checkout(tmp_path), runner=_answering("", ran))

    assert (ran, result.failed, result.holds_the_graphics_card) == ([], False, False)


def test_an_answer_that_cannot_be_read_fails_the_stage_rather_than_passing_in_silence(tmp_path):
    checkout = _checkout(tmp_path, downtime_command=["python.exe", "-m", "origenerator.downtime"])

    result = origenerator_downtime.run(checkout, runner=_answering("Traceback (most recent", []))

    assert (result.failed, result.holds_the_graphics_card) == (True, False)
