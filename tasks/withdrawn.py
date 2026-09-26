"""Delete every clip Origenerator has taken back.

Origenerator hands a finished clip over by copying it, with its funscript when it
has one, into ``0_inbox/<source>/``; the folder is the whole message. Undoing
that is a file delete, and by the time one is asked for -- which is the point,
it can be asked for a long time afterwards -- the clip has been sorted, renamed
by the upscale and, down the Genau lane, moved into a folder outside the
library altogether.
Origenerator knows none of that and must not learn it: it is a content source
like any other, so it records the withdrawal on its own row and this stage
pulls it, the same read-only read ``tasks.origenerator_metadata`` does.

The stamp is a standing answer rather than a request that drains. Nothing on the
other side ever learns that the delete happened, so the row goes on saying the
clip should not be here and this stage goes on finding nothing -- which is also
what makes it self-healing, a copy that somehow reappears being deleted again.
Sending the clip again clears the stamp, and the fresh copy stays.

One clip is several files by the time it is withdrawn -- the inbox copy, the
``1_sorted`` copy, the upscale, the delivered loop -- and the outbox side goes
first: ``check_correspondence`` pops a dialog over a ``1_sorted`` video with no
``_topaz`` counterpart, so an upscale that will not delete (Genau playing it,
usually) leaves its source where it is for the next run to take both together.
"""
from __future__ import annotations

import glob
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import config
from util import lanes, origenerator_gallery, script_library
from util.media_files import child_dirs, library_videos, strip_uniquifier
from util.variants import strip_processing_suffixes

log = logging.getLogger(__name__)


@dataclass
class WithdrawnResult:
    deleted: int = 0
    deleted_metadata: int = 0
    deleted_scripts: int = 0
    failed: int = 0

    def __add__(self, other: WithdrawnResult) -> WithdrawnResult:
        """One result covering both, so each helper returns what it learned
        rather than writing through a result it was handed."""
        return WithdrawnResult(
            deleted=self.deleted + other.deleted,
            deleted_metadata=self.deleted_metadata + other.deleted_metadata,
            deleted_scripts=self.deleted_scripts + other.deleted_scripts,
            failed=self.failed + other.failed)


def run() -> WithdrawnResult:
    """Delete every copy this library holds of a clip Origenerator has withdrawn."""
    result = WithdrawnResult()
    try:
        rows = _gallery_rows()
    except FileNotFoundError:
        # No Origenerator beside this library -- every public checkout, and the
        # ordinary state of a machine that only maintains video.
        return result

    log.info("=== Stage: clips Origenerator has taken back ===")
    for lane in lanes.sent_lanes():
        result = result + _empty_lane(lane, _withdrawn_stems(rows, lane))

    log.info("Withdrawn done. Deleted: %d, deleted metadata: %d, failed: %d",
             result.deleted, result.deleted_metadata, result.failed)
    return result


#: The column this stage selects itself; the withdrawal stamps beside it are
#: each lane's (``util.lanes``). Public for the same reason the metadata
#: stage's are: it is a name another repo keeps for this one.
COLUMNS = ("output_files",)


def _gallery_rows() -> list[dict]:
    """Origenerator's rows, holding the output names and both withdrawal stamps.

    The stamps are optional: a gallery from before they existed has no
    withdrawal to report, which is one more row with nothing set.
    """
    return origenerator_gallery.rows(
        COLUMNS,
        optional=tuple(lane.unsent_column for lane in lanes.sent_lanes()),
    )


def _withdrawn_stems(rows: list[dict], lane: lanes.SentLane) -> set[str]:
    """The stem of every video whose send down *lane* has been taken back.

    A stem rather than a name, because what arrived and what is here now differ
    by everything this library appends: a uniquifier where the name was already
    taken, and the upscale's own suffix.
    """
    stems = set()
    for row in rows:
        if row.get(lane.unsent_column):
            stems.update(Path(name).stem for name in _output_names(row)
                         if _is_video_name(name))
    return stems


def _output_names(row: dict) -> list[str]:
    """The file names a generation row says it produced, or none if it says badly.

    A row is another app's data, so a column holding something other than the
    list of ``{"filename": ...}`` it usually holds costs that one row, not the run.
    """
    try:
        return [entry["filename"] for entry in json.loads(row.get("output_files") or "[]")
                if entry.get("filename")]
    except (AttributeError, TypeError, ValueError):
        log.warning("Could not read what a withdrawn generation produced: %r",
                    row.get("output_files"))
        return []


def _is_video_name(name: str) -> bool:
    return Path(name).suffix.lower() in config.VIDEO_EXTENSIONS


def _empty_lane(lane: lanes.SentLane, stems: set[str]) -> WithdrawnResult:
    """Delete *lane*'s copies of every clip in *stems*, outbox side first.

    The order is the whole of why the groups are kept apart: the outbox and the
    delivered folder hold what a viewer can still reach, and ``1_sorted`` holds
    only what remakes them. Take the reachable copy away and its source follows;
    leave it and the source stays, so the pair is never half gone.
    """
    reachable, sources, waiting = _copy_groups(lane, stems)
    result = _delete_all(reachable)
    if not result.failed:
        result = result + _delete_all(sources)
    return result + _delete_all(waiting)


def _copy_groups(lane: lanes.SentLane,
                 stems: set[str]) -> tuple[list[Path], list[Path], list[Path]]:
    """*lane*'s copies of *stems*, in the three groups they must be deleted in:
    what a viewer can still reach, what remakes it, and what is still waiting to
    be sorted at all."""
    if not stems:
        return ([], [], [])
    return (_reachable_copies(lane, stems),
            _matches([config.SORTED_DIR / lane.source], stems),
            _matches([config.INBOX_DIR / lane.source], stems))


def _reachable_copies(lane: lanes.SentLane, stems: set[str]) -> list[Path]:
    """Every copy a viewer could still reach: the upscale, the delivered loop,
    and either pile a condemned one is waiting in."""
    roots = [*_outbox_dirs(lane), config.WEIRD_DIR]
    if lane.delivered_dir is not None:
        roots += [lane.delivered_dir, config.GENAU_WEIRD_DIR]
    return _matches(roots, stems)


def _outbox_dirs(lane: lanes.SentLane) -> list[Path]:
    """This lane's corner of the outbox -- one folder per orientation.

    Named out rather than searched for, because the outbox is filed by
    orientation and *then* by source: searched whole it would answer for every
    other source's clips too, and two sources' clips can share a stem.
    """
    return [orient / lane.source for orient in child_dirs(config.OUT_UPSCALED_DIR)]


def _matches(roots, stems: set[str]) -> list[Path]:
    """Every video under *roots* whose original name is one of *stems*.

    The piles and the delivered folder are flat and hold whatever was put in
    them, so there the stem is all there is to go on -- and it is enough, being
    the name Origenerator gave the file.
    """
    return [video for root in roots if Path(root).is_dir()
            for video in sorted(library_videos(Path(root)))
            if origin_stem(video.stem) in stems]


def origin_stem(stem: str) -> str:
    """*stem* with everything this library appends taken back off.

    A clip arrives under the name Origenerator gave it, is uniquified if that
    name was taken, upscaled under a ``_topaz`` suffix and uniquified again if
    the delivered folder had it -- so the pair of reductions runs until neither
    one changes anything, rather than once each in an order that leaves what the
    other would have taken off still on the end.
    """
    while True:
        reduced = strip_processing_suffixes(strip_uniquifier(stem))
        if reduced == stem:
            return stem
        stem = reduced


def _delete_all(videos: list[Path]) -> WithdrawnResult:
    """Delete each of *videos*, its sidecars and its funscripts, and say what
    that came to."""
    result = WithdrawnResult()
    for video in videos:
        try:
            video.unlink()
        except OSError:
            # Almost always a clip an app has open right now. It is still a valid
            # library file with everything beside it intact, so leaving it costs
            # nothing and the next run gets it.
            log.warning("Could not delete %s; leaving it for the next run",
                        video.name, exc_info=True)
            result.failed += 1
            continue
        log.info("WITHDRAWN %s", video)
        result.deleted += 1
        result.deleted_metadata += _delete_metadata(video)
        result = result + _delete_scripts(video)
    return result


def _delete_scripts(video: Path) -> WithdrawnResult:
    """Delete *video*'s funscript, mark and all -- and for a 1_sorted copy, the
    one filed with its upscale, which stays there after a viewer condemns the
    upscale until the scripts stage next runs."""
    result = WithdrawnResult()
    for script in script_library.scripts_held_for(video, lanes.upscale_filed_for(video)):
        try:
            script_library.delete_script(script)
        except OSError:
            log.warning("Could not delete %s; leaving it for the next run",
                        script.name, exc_info=True)
            result.failed += 1
            continue
        log.info("Deleted funscript: %s", script)
        result.deleted_scripts += 1
    return result


def _delete_metadata(video: Path) -> int:
    """Remove the mirrored sidecars of a deleted video; how many there were.

    By name across the metadata tree rather than by the one mirrored path, so a
    record left at a path the video has since moved on from goes too.
    """
    if not config.METADATA_DIR.is_dir():
        return 0
    removed = 0
    for record in config.METADATA_DIR.rglob(glob.escape(video.stem) + ".json"):
        record.unlink(missing_ok=True)
        log.info("Deleted metadata: %s", record)
        removed += 1
    return removed
