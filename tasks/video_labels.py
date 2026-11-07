from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from app_support.video_action import labeled

from tasks import origenerator_metadata
from util import lanes, sidecar
from util.stage_result import StageResult

log = logging.getLogger(__name__)

@dataclass
class VideoLabelsResult(StageResult):
    copied: int = 0
    already: int = 0


def run() -> VideoLabelsResult:
    log.info("=== Stage: copy each video's labels from Origenerator ===")
    result = VideoLabelsResult()
    try:
        labels_of = origenerator_metadata.published_labels()
    except (FileNotFoundError, sqlite3.Error):
        log.warning("Could not read Origenerator's gallery; the videos' labels wait for a run "
                    "that can.", exc_info=True)
        return result
    for clip in lanes.ai_videos():
        labels, record = labels_of(clip), sidecar.sidecar_path(clip.upscale)
        if labels is None or not record.exists():
            continue
        if sidecar.update(record, lambda current, labels=labels: labeled(current, labels)) is None:
            result.already += 1
        else:
            result.copied += 1
    log.info("Labels: copied onto %d record(s); %d already carried them.",
             result.copied, result.already)
    return result
