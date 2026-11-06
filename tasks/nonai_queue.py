from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app_support.file_channel import write_whole
from app_support.json_store import read_json_or_empty
from app_support.video_names import strip_processing_suffixes

import config
from util import script_library
from util.media_files import is_finalized_video_file
from util.nonai_library import buckets, stage_dirs
from util.versions import is_processed_stem

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueuedVideo:
    path: Path
    bucket: Path
    triage_digit: int
    has_funscript: bool
    watch_score: float


def collect_queued_videos(*, skip_list: Path, pin_list: Path,
                       watch_stats_file: Path) -> list[QueuedVideo]:
    queued_videos: list[QueuedVideo] = []
    skipped = set(listed_videos(skip_list))
    pinned = listed_videos(pin_list)
    watch_scores = _watch_scores(watch_stats_file)
    for bucket in buckets():
        processed_stems = _processed_stems(bucket)
        for triage_digit, triage_dir in stage_dirs(bucket, digits=(0, 1)):
            for scan_dir in _upscale_ready_dirs(triage_dir):
                for video in sorted(scan_dir.iterdir()):
                    if not is_finalized_video_file(video):
                        continue
                    rel = relpath(video)
                    if is_processed_stem(video.stem):
                        continue
                    if video.stem in processed_stems and rel not in pinned:
                        continue
                    if rel in skipped:
                        continue
                    queued_videos.append(QueuedVideo(
                        video, bucket, triage_digit, _has_funscript(video),
                        watch_scores.get(str(video).strip().lower(), 0.0),
                    ))
    queued_videos.sort(key=lambda c: (
        _pin_rank(pinned, c.path),
        c.triage_digit != 1, -c.watch_score, not c.has_funscript, str(c.path).lower(),
    ))
    return queued_videos


def relpath(video: Path) -> str:
    return video.relative_to(config.NON_AI_DIR).as_posix()


def add_to_skip_list(skip_list: Path, source: Path, reason: str) -> None:
    log.warning("Skipping %s permanently: %s", source, reason)
    with open(skip_list, "a", encoding="utf-8") as handle:
        handle.write(f"{relpath(source)}\t{reason}\n")


def pin_ahead(pin_list: Path, videos: list[str]) -> None:
    lines = _list_lines(pin_list)
    line_of = dict(reversed(lines))
    ahead = [line_of.get(video, video) for video in videos]
    rest = [line for video, line in lines
            if video not in videos and (config.NON_AI_DIR / video).is_file()]
    write_whole(pin_list, "".join(f"{line}\n" for line in ahead + rest))


def listed_videos(path: Path) -> list[str]:
    return [video for video, _line in _list_lines(path)]


def _list_lines(path: Path) -> list[tuple[str, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [(line.split("\t", 1)[0].strip(), line) for line in lines if line.strip()]


def _upscale_ready_dirs(triage_dir: Path) -> list[Path]:
    return [triage_dir] + [d for _, d in stage_dirs(triage_dir, digits=(2, 3))]


def _processed_stems(bucket: Path) -> set[str]:
    stems = set()
    for video in bucket.rglob("*"):
        if is_finalized_video_file(video) and is_processed_stem(video.stem):
            stems.add(strip_processing_suffixes(video.stem))
    return stems


def _watch_scores(path: Path) -> dict[str, float]:
    return {
        key: entry.get("completions", 0) + 3 * entry.get("locks", 0) - entry.get("skips", 0)
        for key, entry in read_json_or_empty(path).items()
        if isinstance(entry, dict)
    }


def _has_funscript(video: Path) -> bool:
    return script_library.script_path_for_video(video).is_file()


def _pin_rank(pinned: list[str], video: Path) -> int:
    try:
        return pinned.index(relpath(video))
    except ValueError:
        return len(pinned)
