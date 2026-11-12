from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

import config
from util.origenerator_gallery import published
from util.stage_result import StageResult

log = logging.getLogger(__name__)

DOWNTIME = "downtime_command"
GALLERY_ENTRIES = "outside_video_entries_command"
RECORDS = "records_command"
_GIVEN_SECONDS = {DOWNTIME: 8 * 60, GALLERY_ENTRIES: 2 * 60, RECORDS: 2 * 60}
_UNANSWERED = (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError)


@dataclass
class DowntimeResult(StageResult):
    did: str = ""
    holds_the_graphics_card: bool = False
    failed: bool = False

    @property
    def ok(self) -> bool:
        return not self.failed


def published_command(checkout: Path, name: str) -> tuple[str, ...] | None:
    try:
        command = tuple(str(part) for part in published(checkout)[name])
    except (KeyError, TypeError):
        return None
    return command or None


def _answer(name: str, checkout: Path | None, runner, *verb: str) -> dict | None:
    checkout = config.ORIGENERATOR_PROJECT_DIR if checkout is None else checkout
    command = published_command(checkout, name)
    if command is None:
        return None
    interpreter, *arguments = command
    answered = runner([str(checkout / interpreter), *arguments, *verb], cwd=str(checkout),
                      capture_output=True, text=True, timeout=_GIVEN_SECONDS[name],
                      **hidden_subprocess_kwargs())
    return json.loads(answered.stdout.strip().splitlines()[-1])


def run_downtime(checkout: Path | None = None, *, runner=subprocess.run) -> DowntimeResult:
    try:
        said = _answer(DOWNTIME, checkout, runner)
        if said is None:
            return DowntimeResult(did="nothing: Origenerator names no work for while it is closed")
        result = DowntimeResult(did=str(said["did"]),
                                holds_the_graphics_card=said["holds_the_graphics_card"] is True)
    except _UNANSWERED as e:
        log.warning("Origenerator's work for while it is closed could not be asked for: %s", e)
        return DowntimeResult(failed=True)
    log.info("Origenerator, while closed: %s%s", result.did,
             "; a LoRA's training holds the graphics card" if result.holds_the_graphics_card else "")
    return result


def write_gallery_entries(checkout: Path | None = None, *, runner=subprocess.run) -> bool:
    try:
        said = _answer(GALLERY_ENTRIES, checkout, runner)
        brought_in = 0 if said is None else int(said["brought_in"])
    except _UNANSWERED as e:
        log.warning("Origenerator's gallery could not be told what the library holds: %s", e)
        return False
    if brought_in:
        log.info("Origenerator's gallery took in %d video(s) other sites made", brought_in)
    return True



@dataclass(frozen=True)
class Handed:
    done: int
    no_row: int


def _run_unseen(*args, **options):
    return subprocess.run(*args, check=False, **options)


class GalleryRecords:
    def __init__(self, checkout: Path | None = None, *, runner=None) -> None:
        self._checkout = checkout
        self._runner = runner

    def record(self, video: Path, record: dict) -> Handed | None:
        return self._hand_over("record", "--video", str(video), record=record)

    def watched(self, totals: dict[Path, dict]) -> Handed | None:
        return self._hand_over("watched",
                               totals={str(video): counts for video, counts in totals.items()})

    def favorite(self, video: Path, starred: bool) -> Handed | None:
        return self._hand_over("favorite", "--video", str(video), "--on" if starred else "--off")

    def upscaled(self, video: Path, provenance: dict) -> Handed | None:
        return self._hand_over("upscaled", "--video", str(video), provenance=provenance)

    def _hand_over(self, *verb: str, **handed: object) -> Handed | None:
        with tempfile.TemporaryDirectory(prefix="evolver-to-the-gallery-") as folder:
            files = []
            for flag, value in handed.items():
                file = Path(folder) / f"{flag}.json"
                file.write_text(json.dumps(value), encoding="utf-8")
                files += [f"--{flag}", str(file)]
            try:
                said = _answer(RECORDS, self._checkout, self._runner or _run_unseen,
                               *verb, *files)
                answer = None if said is None else Handed(int(said["done"]), int(said["no_row"]))
            except _UNANSWERED as e:
                log.warning("%s could not be handed to Origenerator's gallery: %s", verb[0], e)
                return None
        if answer is not None and answer.no_row:
            log.info("Origenerator's gallery has no row for %d of the videos handed it (%s)",
                     answer.no_row, verb[0])
        return answer
