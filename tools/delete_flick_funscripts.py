from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app_support import funscript
from app_support.gallery_rows import VideoRows

import config
from util import lanes, origenerator_gallery, script_library
from util.media_files import library_videos

GOBLINSCRIPT = "made by GoblinScript"
NO_PERSON = "written by no person"
A_PERSON = "written by a person"
KINDS = (GOBLINSCRIPT, NO_PERSON, A_PERSON)
DELETED = (GOBLINSCRIPT, NO_PERSON)
ORIGENERATORS_FOLDER = "Origenerator's videos folder"


@dataclass
class Found:
    by_place: dict[str, dict[Path, str]] = field(default_factory=dict)
    shared_with_a_video: set[Path] = field(default_factory=set)
    origenerator_said: str = ""

    def add(self, place: str, scripts: Iterable[Path]) -> None:
        seen = {script for kept in self.by_place.values() for script in kept}
        self.by_place[place] = {script: _kind_of(script) for script in scripts
                                if script not in seen and script not in self.shared_with_a_video}

    def total(self) -> Counter:
        return Counter(kind for kept in self.by_place.values() for kind in kept.values())


def _kind_of(script: Path) -> str:
    if script_library.made_by_goblinscript(script):
        return GOBLINSCRIPT
    return A_PERSON if script_library.written_by_a_person(script) else NO_PERSON


def _mirrored_scripts(videos: Iterable[Path]) -> list[Path]:
    return [script for video in videos
            if (script := script_library.mirrored_script_of(video)) is not None and script.is_file()]


def _genau_lanes_places() -> dict[str, Iterable[Path]]:
    genau = lanes.genau_source()
    return {
        "Genau's folder": lanes.genau_flicks(),
        "Genau's trash": library_videos(lanes.genau_trash_dir()),
        "`1_sorted`, Genau lane": library_videos(config.SORTED_DIR / genau),
        "`0_inbox`, Genau lane": library_videos(config.INBOX_DIR / genau),
    }


def _places_of(video: Path) -> list[Path]:
    return funscript.places_a_script_may_be_kept(
        video, videos=config.ORIGENERATOR_VIDEOS_DIR, scripts=config.ORIGENERATOR_SCRIPTS_DIR)


def _origenerators_flicks(found: Found, checkout: Path) -> None:
    flick_workflows = origenerator_gallery.flick_workflows(checkout)
    if not flick_workflows:
        found.origenerator_said = "Origenerator has not said which of its files are flicks yet: 0 looked at"
        return
    try:
        rows = origenerator_gallery.rows(("prompt_id", "output_files"),
                                         optional=("workflow_name", origenerator_gallery.EVOLVER_UPSCALE))
    except (FileNotFoundError, sqlite3.Error):
        found.origenerator_said = "Origenerator's gallery could not be read: 0 looked at"
        return
    workflow_of = {row["prompt_id"]: row.get("workflow_name") for row in rows}
    row_of = VideoRows(rows)
    videos = list(library_videos(config.ORIGENERATOR_VIDEOS_DIR))
    flicks = [video for video in videos if workflow_of.get(row_of(video) or "") in flick_workflows]
    taken_by_videos = {place for video in videos if video not in flicks for place in _places_of(video)}
    scripts = [place for flick in flicks for place in _places_of(flick) if place.is_file()]
    found.shared_with_a_video |= {script for script in scripts if script in taken_by_videos}
    found.add(ORIGENERATORS_FOLDER, scripts)
    found.origenerator_said = f"({len(videos)} looked at, {len(flicks)} of them flicks)"


def find(checkout: Path) -> Found:
    found = Found()
    for place, videos in _genau_lanes_places().items():
        found.add(place, _mirrored_scripts(videos))
    _origenerators_flicks(found, checkout)
    return found


def _counts(counted: Counter, kinds: Iterable[str] = KINDS) -> str:
    return ", ".join(f"{counted[kind]} {kind}" for kind in kinds)


def _report(found: Found) -> list[str]:
    _, flicks = config.GENAU_FLICK_WORDS
    lines = [f"Funscripts kept for Genau {flicks}:"]
    for place, kept in found.by_place.items():
        line = f"  {place}: {_counts(Counter(kept.values()))}"
        lines.append(f"{line} {found.origenerator_said}" if place == ORIGENERATORS_FOLDER else line)
    if ORIGENERATORS_FOLDER not in found.by_place:
        lines.append(f"  {found.origenerator_said}")
    lines.append(f"  Total: {_counts(found.total())}")
    if found.shared_with_a_video:
        lines.append(f"Left, since a video of the same name may use them: {len(found.shared_with_a_video)}")
    return lines


def _delete(found: Found) -> list[str]:
    deleted: Counter = Counter()
    failed = 0
    for kept in found.by_place.values():
        for script, kind in kept.items():
            if kind not in DELETED:
                continue
            try:
                script_library.delete_script(script)
            except OSError:
                failed += 1
                continue
            deleted[kind] += 1
    lines = [f"Deleted: {_counts(deleted, DELETED)}"]
    if failed:
        lines.append(f"Could not be deleted, left for the next run: {failed}")
    return [*lines, f"Left, since a person wrote them: {found.total()[A_PERSON]}"]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Count, and with --apply delete, the funscripts kept for Genau flicks that no person wrote.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--origenerator", type=Path, default=None,
                        help="the Origenerator checkout whose published contract says which workflows make flicks")
    arguments = parser.parse_args(argv)
    found = find(arguments.origenerator or origenerator_gallery.origenerators_checkout())
    lines = _report(found)
    if arguments.apply:
        lines += _delete(found)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
