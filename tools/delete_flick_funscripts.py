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
from app_support.gallery_rows import VideoRows, is_video_name, output_names
from app_support.trash_names import name_before_trash
from app_support.video_names import strip_uniquifier

import config
from util import lanes, origenerator_gallery, script_library
from util.media_files import library_videos
from util.versions import sorted_stem_of, upscaled_stem

GOBLINSCRIPT = "made by GoblinScript"
NO_PERSON = "written by no person"
A_PERSON = "written by a person"
KINDS = (GOBLINSCRIPT, NO_PERSON, A_PERSON)
DELETED = (GOBLINSCRIPT, NO_PERSON)
ORIGENERATORS_FOLDER = "Origenerator's videos folder"
NOT_SAID = "Origenerator has not said which of its files are flicks yet: 0 looked at"


@dataclass
class Found:
    by_place: dict[str, dict[Path, str]] = field(default_factory=dict)
    shared_with_a_video: set[Path] = field(default_factory=set)
    origenerator_said: str = ""
    flick_names: set[str] = field(default_factory=set)
    video_names: set[str] = field(default_factory=set)

    def add(self, place: str, scripts: Iterable[Path]) -> None:
        seen = {script for kept in self.by_place.values() for script in kept}
        self.by_place[place] = {script: _kind_of(script) for script in scripts
                                if script not in seen and script not in self.shared_with_a_video}

    def add_left_without_a_video(self, place: str, scripts: Iterable[Path], *, all_flicks: bool) -> None:
        seen = {script for kept in self.by_place.values() for script in kept}
        named = [script for script in scripts if script not in seen
                 and (all_flicks or _name_of(script) in self.flick_names)]
        self.shared_with_a_video |= {script for script in named if _name_of(script) in self.video_names}
        self.add(place, named)

    def total(self) -> Counter:
        return Counter(kind for kept in self.by_place.values() for kind in kept.values())


def _kind_of(script: Path) -> str:
    if script_library.made_by_goblinscript(script):
        return GOBLINSCRIPT
    return A_PERSON if script_library.written_by_a_person(script) else NO_PERSON


def _name_of(script: Path) -> str:
    return strip_uniquifier(script.stem)


def _names_down_the_lane(stem: str) -> set[str]:
    as_sorted = sorted_stem_of(stem)
    return {as_sorted, upscaled_stem(as_sorted)}


def _mirrored_scripts(videos: Iterable[Path]) -> list[Path]:
    return [script for video in videos
            if (script := script_library.mirrored_script_of(video)) is not None and script.is_file()]


def _funscripts_in(folder: Path | None) -> list[Path]:
    if folder is None or not folder.is_dir():
        return []
    return sorted(path for path in folder.rglob(f"*{funscript.EXTENSION}") if path.is_file())


def _genau_lanes_folders() -> dict[str, Path | None]:
    genau = lanes.genau_source()
    return {
        "Genau's folder": lanes.genau_flicks_dir(),
        "Genau's trash": lanes.genau_trash_dir(),
        "`1_sorted`, Genau lane": config.SORTED_DIR / genau,
        "`0_inbox`, Genau lane": config.INBOX_DIR / genau,
    }


def _the_genau_lane(found: Found) -> None:
    for place, folder in _genau_lanes_folders().items():
        videos = [] if folder is None else list(library_videos(folder))
        found.flick_names |= {name for video in videos
                              for name in _names_down_the_lane(Path(name_before_trash(video.name)).stem)}
        found.add(place, _mirrored_scripts(videos))


def _places_of(video: Path) -> list[Path]:
    return funscript.places_a_script_may_be_kept(
        video, videos=config.ORIGENERATOR_VIDEOS_DIR, scripts=config.ORIGENERATOR_SCRIPTS_DIR)


def _names_in(rows: Iterable[dict]) -> set[str]:
    return {name for row in rows for made in output_names(row) if is_video_name(made)
            for name in _names_down_the_lane(Path(made).stem)}


def _origenerators_flicks(found: Found, checkout: Path) -> None:
    flick_workflows = origenerator_gallery.flick_workflows(checkout)
    if not flick_workflows:
        found.origenerator_said = NOT_SAID
        return
    try:
        rows = origenerator_gallery.rows(("prompt_id", "output_files"),
                                         optional=("workflow_name", origenerator_gallery.EVOLVER_UPSCALE))
    except (FileNotFoundError, sqlite3.Error):
        found.origenerator_said = "Origenerator's gallery could not be read: 0 looked at"
        return
    flick_rows = [row for row in rows if row.get("workflow_name") in flick_workflows]
    found.flick_names |= _names_in(flick_rows)
    found.video_names |= _names_in(row for row in rows if row.get("workflow_name") not in flick_workflows)
    flick_ids = {row["prompt_id"] for row in flick_rows}
    row_of = VideoRows(rows)
    videos = list(library_videos(config.ORIGENERATOR_VIDEOS_DIR))
    flicks = [video for video in videos if row_of(video) in flick_ids]
    taken_by_videos = {place for video in videos if video not in flicks for place in _places_of(video)}
    scripts = [place for flick in flicks for place in _places_of(flick) if place.is_file()]
    found.shared_with_a_video |= {script for script in scripts if script in taken_by_videos}
    found.video_names |= {video.stem for video in videos if video not in flicks}
    found.add(ORIGENERATORS_FOLDER, scripts)
    found.origenerator_said = f"({len(videos)} looked at, {len(flicks)} of them flicks)"


def _video_names_outside_the_genau_lane() -> set[str]:
    lane = [folder for folder in _genau_lanes_folders().values() if folder is not None]
    kept = [config.VIDEO_LIBRARY_DIR, config.NONAI_RETIRED_ROOT]
    in_the_library = {video.stem for root in kept if root is not None for video in library_videos(root)
                      if not any(video.is_relative_to(folder) for folder in lane)}
    return in_the_library | {vr.in_library.stem for vr in lanes.vr_videos()}


def _left_without_their_video(found: Found) -> None:
    lane_scripts = [script for folder in _genau_lanes_folders().values() if folder is not None
                    for script in _funscripts_in(script_library.scripts_folder_for(folder))]
    found.add_left_without_a_video("Scripts folder, Genau lane, video gone", lane_scripts, all_flicks=True)
    found.add_left_without_a_video("`unmatched_scripts`", _funscripts_in(config.UNMATCHED_SCRIPTS_DIR),
                                   all_flicks=False)
    found.add_left_without_a_video("Non-AI archive", _funscripts_in(config.NONAI_RETIRED_ROOT),
                                   all_flicks=False)


def find(checkout: Path) -> Found:
    found = Found()
    _the_genau_lane(found)
    _origenerators_flicks(found, checkout)
    found.video_names |= _video_names_outside_the_genau_lane()
    _left_without_their_video(found)
    return found


def _counts(counted: Counter, kinds: Iterable[str] = KINDS) -> str:
    return ", ".join(f"{counted[kind]} {kind}" for kind in kinds)


def _report(found: Found) -> list[str]:
    _, flicks = config.GENAU_FLICK_WORDS
    lines = [f"Funscripts kept for Genau {flicks}:"]
    for place, kept in found.by_place.items():
        line = f"  {place}: {_counts(Counter(kept.values()))}"
        lines.append(f"{line} {found.origenerator_said}" if place == ORIGENERATORS_FOLDER else line)
        if place == "`0_inbox`, Genau lane" and ORIGENERATORS_FOLDER not in found.by_place:
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
