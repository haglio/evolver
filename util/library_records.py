from __future__ import annotations

from app_support import favorites, video_ids, watch_weights
from app_support.video_kind import TYPES
from shared_ui.orientation import ORIENTATIONS

from util import scene_links, video_kind, watch
from util.sidecar import WRONG_ACTION_FIELD

VIDEO_BLOCK = video_kind.BLOCK

VIDEO_TYPE_FIELD = video_kind.FIELD
VIDEO_DURATION_FIELD = video_kind.DURATION_FIELD
VIDEO_ORIENTATION_FIELD = video_kind.ORIENTATION_FIELD
VIDEO_ACTION_FIELD = "action"
VIDEO_WRONG_ACTION_FIELD = WRONG_ACTION_FIELD
VIDEO_FIELDS_FUN_TIME_WRITES = (VIDEO_WRONG_ACTION_FIELD,)

VIDEO_KINDS = TYPES


CLIP_BLOCK = scene_links.BLOCK
CLIP_PERFORMER_FIELD = "performer"
CLIP_SOURCE_FIELD = "source"
CLIP_SCENE_ID_FIELD = scene_links.SCENE_ID
CLIP_SCENE_OFFSET_FIELD = "scene_offset"
CLIP_FIELDS_WRITTEN_WHEN_A_CLIP_IS_CUT = (CLIP_PERFORMER_FIELD, CLIP_SOURCE_FIELD)
CLIP_FIELDS_THE_CLIP_MATCH_ADDS = (CLIP_SCENE_ID_FIELD, CLIP_SCENE_OFFSET_FIELD)

VERSION_BLOCK = "version"
VERSION_GROUP_FIELD = "group"

WATCH_BLOCK = watch.BLOCK
WATCH_COUNT_FIELDS = watch_weights.COUNT_FIELDS
WATCH_WEIGHT_FIELD = watch.WEIGHT_FIELD

TITLE_KEY = "title"
FAVORITE_KEY = favorites.FAVORITE_KEY
PAGE_KEY = favorites.PAGE_KEY
ID_KEY = video_ids.ID_KEY


def promised_to_fun_time() -> dict:
    return {
        "blocks": {
            VIDEO_BLOCK: {
                "fields": [
                    VIDEO_TYPE_FIELD,
                    VIDEO_DURATION_FIELD,
                    VIDEO_ORIENTATION_FIELD,
                    VIDEO_ACTION_FIELD,
                    VIDEO_WRONG_ACTION_FIELD,
                ],
                "written_by_the_reader": list(VIDEO_FIELDS_FUN_TIME_WRITES),
            },
            CLIP_BLOCK: {"fields": [*CLIP_FIELDS_WRITTEN_WHEN_A_CLIP_IS_CUT, *CLIP_FIELDS_THE_CLIP_MATCH_ADDS]},
            VERSION_BLOCK: {"fields": [VERSION_GROUP_FIELD]},
            WATCH_BLOCK: {
                "fields": [*WATCH_COUNT_FIELDS, WATCH_WEIGHT_FIELD],
            },
        },
        "top_level_keys": [TITLE_KEY, FAVORITE_KEY, PAGE_KEY, ID_KEY],
        "top_level_written_by_the_reader": [FAVORITE_KEY, PAGE_KEY, ID_KEY],
        "video_kinds": list(VIDEO_KINDS),
        "video_orientations": list(ORIENTATIONS),
    }
