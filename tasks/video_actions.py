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
class VideoActionsResult(StageResult):
    copied: int = 0
    already: int = 0


def run() -> VideoActionsResult:
    log.info("=== Stage: copy each video's actions from Origenerator ===")
    result = VideoActionsResult()
    try:
        actions_of = origenerator_metadata.published_actions()
    except (FileNotFoundError, sqlite3.Error):
        log.warning("Could not read Origenerator's gallery; the videos' actions wait for a run "
                    "that can.", exc_info=True)
        return result
    for clip in lanes.ai_videos():
        actions, record = actions_of(clip), sidecar.sidecar_path(clip.upscale)
        if actions is None or not record.exists():
            continue
        if sidecar.update(record, lambda current, actions=actions: labeled(current, actions)) is None:
            result.already += 1
        else:
            result.copied += 1
    log.info("Actions: copied onto %d sidecar(s); %d already had them.",
             result.copied, result.already)
    return result
