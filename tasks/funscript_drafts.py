from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app_support import funscript, processes
from app_support.file_channel import write_whole
from app_support.json_store import read_json_or_empty
from app_support.subprocess_utils import hidden_subprocess_kwargs

from util import lanes
from util.media_files import library_videos
from util.script_library import mark_generated, script_path_for_video
from util.stage_result import StageResult

log = logging.getLogger(__name__)

RELEASE = "v0.6.0"
PROJECT = "evolver"
CREATOR = f"GoblinScript {RELEASE}"
STILL_DRAFTING = "goblinscript_still_drafting"
GOBLINSCRIPT_FAILED = "goblinscript_failed"
GOBLINSCRIPT_MISSING = "goblinscript_not_installed"
HOLD_OFF_AFTER_A_FAILURE_SECONDS = 60 * 60
DRAFTS_PER_RUN = 60

_BATCH = "batch"
_NOTHING_USABLE = "nothing_usable"
_FAILED_AT = "failed_at"
_FEWEST_ACTIONS_OF_A_USABLE_DRAFT = 2


@dataclass
class FunscriptDraftsResult(StageResult):
    made: int = 0
    nothing_usable: int = 0
    started: int = 0
    waiting: int = 0
    failed_batches: int = 0

    @property
    def ok(self) -> bool:
        return not self.failed_batches


@dataclass(frozen=True)
class Goblin:
    home: Path

    @property
    def python(self) -> Path:
        return self.home / "venv" / "Scripts" / "python.exe"

    @property
    def trainer(self) -> Path:
        return self.home / "GoblinTrainingGrounds" / "goblintrain.py"

    def is_installed(self) -> bool:
        return self.python.is_file() and self.trainer.is_file()

    @property
    def project(self) -> Path:
        return self.home / "GoblinTrainingGrounds" / "projects" / PROJECT

    def draft_command(self, videos: list[Path], out: Path) -> list[str]:
        return [str(self.python), str(self.trainer), "draft", *map(str, videos),
                "--out", str(out), "--force", "--project", PROJECT, "--model", RELEASE]


@dataclass(frozen=True)
class Drafting:
    drafts: Path
    log: Path
    record: Path

    @classmethod
    def kept_in(cls, folder: Path) -> Drafting:
        return cls(drafts=folder / "funscript_drafts", log=folder / "funscript_drafts.log",
                   record=folder / "funscript_drafts.json")

    def read(self) -> dict:
        return read_json_or_empty(self.record)

    def write(self, record: dict) -> None:
        write_whole(self.record, json.dumps(record, indent=2))


def launch(command: list[str], log: Path, *, popen=subprocess.Popen) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "w", encoding="utf-8") as errors:
        return popen(command, stdout=subprocess.DEVNULL, stderr=errors,
                     **hidden_subprocess_kwargs(creationflags=subprocess.BELOW_NORMAL_PRIORITY_CLASS)).pid


def drafting_by(goblin: Goblin) -> Callable[[int], bool]:
    def still_running(pid: int) -> bool:
        return (processes.is_running(pid)
                and os.path.normcase(processes.exe_of(pid)) == os.path.normcase(goblin.python))
    return still_running


def hold_off_reason(*, goblin: Goblin | None, drafting: Drafting,
                    still_running: Callable[[int], bool] | None = None,
                    now: float | None = None) -> str:
    if goblin is None or not goblin.is_installed():
        return GOBLINSCRIPT_MISSING
    record = drafting.read()
    batch = record.get(_BATCH)
    if batch and (still_running or drafting_by(goblin))(batch["pid"]):
        return STILL_DRAFTING
    failed_at = record.get(_FAILED_AT)
    if failed_at is not None and _now(now) - failed_at < HOLD_OFF_AFTER_A_FAILURE_SECONDS:
        return GOBLINSCRIPT_FAILED
    return ""


def _now(now: float | None) -> float:
    return time.time() if now is None else now


def run(*, goblin: Goblin, drafting: Drafting,
        start: Callable[[list[str], Path], int] = launch,
        still_running: Callable[[int], bool] | None = None,
        max_items: int = DRAFTS_PER_RUN,
        now: float | None = None) -> FunscriptDraftsResult:
    if hold_off_reason(goblin=goblin, drafting=drafting, still_running=still_running, now=now):
        return FunscriptDraftsResult()
    record = drafting.read()
    made = _take_in_the_finished_batch(goblin, drafting, record)
    if made is None:
        record[_FAILED_AT] = _now(now)
        drafting.write(record)
        log.error("GoblinScript wrote no funscript for its last batch; see %s. The stage holds off "
                  "for an hour, then sends those videos again.", drafting.log)
        return FunscriptDraftsResult(nothing_usable=len(record.get(_NOTHING_USABLE, ())),
                                     failed_batches=1)
    nothing_usable = set(record.get(_NOTHING_USABLE, ()))
    waiting = [upscale for upscale in _waiting_newest_first() if _key(upscale) not in nothing_usable]
    batch = _one_of_each_name(waiting)[:max_items]
    if batch:
        pid = start(goblin.draft_command(batch, drafting.drafts), drafting.log)
        record[_BATCH] = {"pid": pid, "videos": list(map(str, batch))}
    drafting.write(record)
    return _logged(FunscriptDraftsResult(made=made, nothing_usable=len(nothing_usable),
                                         started=len(batch), waiting=len(waiting) - len(batch)))


def _logged(result: FunscriptDraftsResult) -> FunscriptDraftsResult:
    log.info("Funscripts made: %d. Videos GoblinScript drafted nothing usable for: %d. "
             "Sent to GoblinScript now: %d. Still waiting: %d.",
             result.made, result.nothing_usable, result.started, result.waiting)
    return result


def _one_of_each_name(videos: list[Path]) -> list[Path]:
    first_of_each = {}
    for video in videos:
        first_of_each.setdefault(video.stem.lower(), video)
    return list(first_of_each.values())


def _take_in_the_finished_batch(goblin: Goblin, drafting: Drafting, record: dict) -> int | None:
    batch = record.pop(_BATCH, None)
    if batch is None:
        return 0
    wrote_nothing = not any(drafting.drafts.glob(f"*{funscript.EXTENSION}"))
    if wrote_nothing:
        _clear_the_batch_away(goblin, drafting)
        return None
    made = 0
    nothing_usable = record.setdefault(_NOTHING_USABLE, [])
    has_a_funscript = _HasAFunscript()
    for video in map(Path, batch["videos"]):
        draft = funscript.read(drafting.drafts / f"{video.stem}{funscript.EXTENSION}")
        if len(funscript.actions_of(draft)) < _FEWEST_ACTIONS_OF_A_USABLE_DRAFT:
            nothing_usable.append(_key(video))
        elif video.is_file() and not has_a_funscript(video):
            _place(video, draft)
            made += 1
    _clear_the_batch_away(goblin, drafting)
    return made


def _clear_the_batch_away(goblin: Goblin, drafting: Drafting) -> None:
    shutil.rmtree(drafting.drafts, ignore_errors=True)
    shutil.rmtree(goblin.project, ignore_errors=True)


def _key(upscale: Path) -> str:
    return upscale.relative_to(lanes.kino_upscales_dir()).as_posix()


def _place(video: Path, draft: dict) -> None:
    metadata = draft.get(funscript.METADATA)
    metadata = metadata if isinstance(metadata, dict) else {}
    script = script_path_for_video(video)
    funscript.write(script, {**draft, funscript.METADATA: {**metadata, "creator": CREATOR}})
    mark_generated(script)


class _HasAFunscript:
    def __init__(self) -> None:
        self._sorted_video_scripted = {ai.upscale for ai in lanes.ai_videos()
                                       if script_path_for_video(ai.video).exists()}

    def __call__(self, upscale: Path) -> bool:
        return script_path_for_video(upscale).exists() or upscale in self._sorted_video_scripted


def _waiting_newest_first() -> list[Path]:
    has_a_funscript = _HasAFunscript()
    waiting = [upscale for upscale in library_videos(lanes.kino_upscales_dir())
               if not has_a_funscript(upscale)]
    return sorted(waiting, key=lambda upscale: upscale.stat().st_mtime, reverse=True)
