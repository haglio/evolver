from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from app_support import funscript, gallery_rows, processes
from app_support.file_channel import write_whole
from app_support.json_store import read_json_or_empty
from app_support.subprocess_utils import hidden_subprocess_kwargs

from tasks import vr_draft
from util import lanes
from util.media_files import library_videos
from util.script_library import is_marked_generated, mark_generated, script_path_for_video
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
BARELY_MOVING_TRAVEL_PER_SECOND = 20.0
BARELY_MOVING_SPREAD = 15
HELD_FLAT_NOTE = "Flat: GoblinScript found very little movement in this video."

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
    already_scripted: int = 0

    @property
    def ok(self) -> bool:
        return not self.failed_batches


@dataclass(frozen=True)
class Library:
    videos: Path
    sorted_videos: Path
    gallery: Path
    origenerator_videos: Path
    origenerator_scripts: Path
    actions_given_no_funscript: frozenset[str] = frozenset()


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
    flattened: Path
    replaced: Path
    log: Path
    record: Path

    @classmethod
    def kept_in(cls, folder: Path) -> Drafting:
        return cls(drafts=folder / "funscript_drafts", flattened=folder / "funscript_drafts_flat",
                   replaced=folder / "funscript_drafts_replaced", log=folder / "funscript_drafts.log",
                   record=folder / "funscript_drafts.json")

    def command_for(self, goblin: Goblin, batch: list[Waiting]) -> list[str]:
        if batch[0].is_vr:
            flat = self.flattened / f"{batch[0].video.stem}.mp4"
            return [str(goblin.python), str(vr_draft.__file__), str(batch[0].video), str(flat), "--",
                    *goblin.draft_command([flat], self.drafts)]
        return goblin.draft_command([waiting.video for waiting in batch], self.drafts)

    def read(self) -> dict:
        return read_json_or_empty(self.record)

    def write(self, record: dict) -> None:
        write_whole(self.record, json.dumps(record, indent=2))


@dataclass(frozen=True)
class Waiting:
    video: Path
    script: Path
    is_vr: bool = False

    @classmethod
    def in_the_library(cls, video: Path) -> Waiting:
        return cls(video, script_path_for_video(video))


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


def run(*, library: Library, goblin: Goblin, drafting: Drafting,
        start: Callable[[list[str], Path], int] = launch,
        still_running: Callable[[int], bool] | None = None,
        max_items: int = DRAFTS_PER_RUN,
        now: float | None = None) -> FunscriptDraftsResult:
    if hold_off_reason(goblin=goblin, drafting=drafting, still_running=still_running, now=now):
        return FunscriptDraftsResult()
    record = drafting.read()
    made = _take_in_the_finished_batch(library, goblin, drafting, record)
    if made is None:
        record[_FAILED_AT] = _now(now)
        drafting.write(record)
        log.error("GoblinScript wrote no funscript for its last batch; see %s. The stage holds off "
                  "for an hour, then sends those videos again.", drafting.log)
        return FunscriptDraftsResult(nothing_usable=len(record.get(_NOTHING_USABLE, ())),
                                     failed_batches=1)
    nothing_usable = set(record.get(_NOTHING_USABLE, ()))
    looked_over = _looked_over(library)
    waiting = [one for one in looked_over.waiting if _key(one.script) not in nothing_usable]
    batch = _next_batch(waiting, max_items)
    if batch:
        pid = start(drafting.command_for(goblin, batch), drafting.log)
        record[_BATCH] = {"pid": pid, "videos": [str(one.video) for one in batch],
                          "scripts": [str(one.script) for one in batch], "vr": batch[0].is_vr}
    drafting.write(record)
    return _logged(FunscriptDraftsResult(made=made, nothing_usable=len(nothing_usable),
                                         started=len(batch), waiting=len(waiting) - len(batch),
                                         already_scripted=looked_over.already_scripted))


def _logged(result: FunscriptDraftsResult) -> FunscriptDraftsResult:
    log.info("Funscripts made: %d. Videos GoblinScript drafted nothing usable for: %d. "
             "Sent to GoblinScript now: %d. Still waiting: %d.",
             result.made, result.nothing_usable, result.started, result.waiting)
    return result


def _next_batch(waiting: list[Waiting], max_items: int) -> list[Waiting]:
    flat = [one for one in waiting if not one.is_vr]
    if not flat:
        return waiting[:1]
    first_of_each = {}
    for one in flat:
        first_of_each.setdefault(one.video.stem.lower(), one)
    return list(first_of_each.values())[:max_items]


def _take_in_the_finished_batch(library: Library, goblin: Goblin, drafting: Drafting,
                                record: dict) -> int | None:
    batch = record.pop(_BATCH, None)
    if batch is None:
        return 0
    wrote_nothing = not any(drafting.drafts.glob(f"*{funscript.EXTENSION}"))
    if wrote_nothing:
        _clear_the_batch_away(goblin, drafting)
        return None
    made = 0
    nothing_usable = record.setdefault(_NOTHING_USABLE, [])
    settled = _Settled(library)
    for video, script in zip(map(Path, batch["videos"]), map(Path, batch["scripts"]), strict=True):
        draft = funscript.read(drafting.drafts / f"{video.stem}{funscript.EXTENSION}")
        if len(funscript.actions_of(draft)) < _FEWEST_ACTIONS_OF_A_USABLE_DRAFT:
            nothing_usable.append(_key(script))
        elif (batch.get("vr") or video.is_file()) and not settled.script(script):
            _keep_what_it_replaces(script, drafting)
            _place(script, draft)
            made += 1
    _clear_the_batch_away(goblin, drafting)
    return made


def _clear_the_batch_away(goblin: Goblin, drafting: Drafting) -> None:
    shutil.rmtree(drafting.drafts, ignore_errors=True)
    shutil.rmtree(drafting.flattened, ignore_errors=True)
    shutil.rmtree(goblin.project, ignore_errors=True)


def _key(script: Path) -> str:
    return script.as_posix()


def _keep_what_it_replaces(script: Path, drafting: Drafting) -> None:
    if script.is_file():
        kept = drafting.replaced / script.relative_to(script.anchor)
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(script, kept)


def _place(script: Path, draft: dict) -> None:
    metadata = draft.get(funscript.METADATA)
    metadata = metadata if isinstance(metadata, dict) else {}
    placed = {**draft, funscript.METADATA: {**metadata, "creator": CREATOR}}
    funscript.write(script, _held_flat(placed) if _barely_moves(placed) else placed)
    mark_generated(script)


def _barely_moves(draft: dict) -> bool:
    moves = sorted((action["at"], action["pos"]) for action in funscript.actions_of(draft))
    seconds = (moves[-1][0] - moves[0][0]) / 1000 or 1.0
    travel_per_second = sum(abs(after[1] - before[1]) for before, after in pairwise(moves)) / seconds
    spots = sorted(pos for _, pos in moves)
    spread = spots[max(int(0.9 * len(spots)) - 1, 0)] - spots[int(0.1 * len(spots))]
    return travel_per_second < BARELY_MOVING_TRAVEL_PER_SECOND or spread < BARELY_MOVING_SPREAD


def _held_flat(draft: dict) -> dict:
    end = max(1000, *(action["at"] for action in funscript.actions_of(draft)))
    metadata = {**draft[funscript.METADATA], "description": HELD_FLAT_NOTE}
    return {**draft, funscript.METADATA: metadata, funscript.ACTIONS: [{"at": 0, "pos": 0}, {"at": end, "pos": 0}]}


class _Settled:
    def __init__(self, library: Library) -> None:
        self._origenerators = library.origenerator_scripts
        self._twin = {}
        for ai in lanes.ai_videos():
            self._twin[ai.upscale] = ai.video
            self._twin[ai.video] = ai.upscale

    def video(self, video: Path) -> bool:
        twin = self._twin.get(video)
        return any(self.script(script_path_for_video(one)) for one in (video, twin) if one is not None)

    def script(self, script: Path) -> bool:
        return script.is_file() and not self._written_by_no_person_and_not_by_goblinscript(script)

    def _written_by_no_person_and_not_by_goblinscript(self, script: Path) -> bool:
        written_by_no_person = script.is_relative_to(self._origenerators) or is_marked_generated(script)
        return written_by_no_person and not _made_by_goblinscript(script)


def _made_by_goblinscript(script: Path) -> bool:
    metadata = funscript.read(script).get(funscript.METADATA)
    return isinstance(metadata, dict) and str(metadata.get("creator") or "").startswith("GoblinScript")


def _sorted_videos_not_yet_upscaled(library: Library) -> list[Path]:
    if not library.sorted_videos.is_dir():
        return []
    return [video for video in library_videos(library.sorted_videos)
            if not lanes.is_genau_lane(video.relative_to(library.sorted_videos).parts[0])
            and not (lanes.upscale_filed_for(video) or Path()).is_file()]


def _given_no_funscript(library: Library) -> Callable[[Path], bool]:
    left_out = library.actions_given_no_funscript
    if not left_out:
        return lambda video: False
    found = gallery_rows.rows(("prompt_id", "output_files", "evolver_upscale", "video_actions"),
                              db_path=library.gallery)
    actions_by_id = {row["prompt_id"]: _actions_in(row) for row in found}
    row_of = gallery_rows.VideoRows(found)

    def every_action_is_given_no_funscript(video: Path) -> bool:
        actions = actions_by_id.get(row_of(video) or "", set())
        return bool(actions) and actions <= left_out
    return every_action_is_given_no_funscript


def _actions_in(row: dict) -> set[str]:
    try:
        actions = json.loads(row.get("video_actions") or "[]")
    except ValueError:
        return set()
    return set(actions) if isinstance(actions, list) else set()


@dataclass(frozen=True)
class _LookedOver:
    waiting: list[Waiting]
    already_scripted: int


def _looked_over(library: Library) -> _LookedOver:
    settled = _Settled(library)
    given_no_funscript = _given_no_funscript(library)
    videos = [*library_videos(lanes.kino_upscales_dir()), *_sorted_videos_not_yet_upscaled(library),
              *lanes.non_ai_videos()]
    in_the_library = [Waiting.in_the_library(video) for video in videos if not settled.video(video)]
    origenerators_own = _origenerators_own(library, settled)
    waiting = sorted((one for one in [*in_the_library, *origenerators_own.waiting]
                      if not given_no_funscript(one.video)),
                     key=lambda one: one.video.stat().st_mtime, reverse=True)
    vr_videos = list(lanes.vr_videos())
    vr = [Waiting(vr.video, script_path_for_video(vr.in_library), is_vr=True) for vr in vr_videos
          if not settled.script(script_path_for_video(vr.in_library))]
    already_scripted = (len(videos) - len(in_the_library) + origenerators_own.already_scripted
                        + len(vr_videos) - len(vr))
    return _LookedOver([*waiting, *vr], already_scripted)


def _origenerators_own(library: Library, settled: _Settled) -> _LookedOver:
    if not library.origenerator_videos.is_dir():
        return _LookedOver([], 0)
    waiting = []
    videos = list(library_videos(library.origenerator_videos))
    for video in videos:
        places = funscript.places_a_script_may_be_kept(
            video, videos=library.origenerator_videos, scripts=library.origenerator_scripts)
        kept = next((place for place in places if place.is_file()), None)
        if kept is None or not settled.script(kept):
            waiting.append(Waiting(video, kept or places[0]))
    return _LookedOver(waiting, len(videos) - len(waiting))
