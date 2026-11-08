from __future__ import annotations

from app_support import favorites, video_ids
from shared_ui.orientation import ORIENTATIONS

from util import scene_links, video_kind, watch
from util.sidecar import WRONG_ACTION_FIELD

VIDEO_BLOCK = video_kind.BLOCK

VIDEO_TYPE_FIELD = video_kind.FIELD
VIDEO_DURATION_FIELD = video_kind.DURATION_FIELD
VIDEO_ORIENTATION_FIELD = video_kind.ORIENTATION_FIELD
VIDEO_ACTION_FIELD = "action"
VIDEO_WRONG_ACTION_FIELD = WRONG_ACTION_FIELD

VIDEO_KINDS = video_kind.TYPES

VIDEO_GENERATION_FIELDS = (
    "prompt", "model", "resolution", "aspect_ratio", "quality", "style",
    "seed", "created",
)

SOURCE_IMAGE_BLOCK = "source_image"
FRAME_OF_VIDEO_BLOCK = "frame_of_video"
SOURCE_IMAGE_FIELDS = (
    "positive_prompt", "negative_prompt", "model", "action", "resolution",
    "aspect_ratio", "quality", "style", "creativity", "seed", "created", FRAME_OF_VIDEO_BLOCK,
)

CLIP_BLOCK = "clip"
CLIP_FIELDS = ("performer", "source", scene_links.SCENE_ID, "scene_offset")

VERSION_BLOCK = "version"
VERSION_GROUP_FIELD = "group"

WATCH_BLOCK = watch.BLOCK
WATCH_COUNT_FIELDS = watch.COUNT_FIELDS
WATCH_WEIGHT_FIELD = "weight"

TITLE_KEY = "title"
FAVORITE_KEY = favorites.FAVORITE_KEY
PAGE_KEY = favorites.PAGE_KEY
ID_KEY = video_ids.ID_KEY


def declaration() -> dict:
    return {
        "blocks": {
            VIDEO_BLOCK: {
                "fields": [
                    VIDEO_TYPE_FIELD,
                    VIDEO_DURATION_FIELD,
                    VIDEO_ORIENTATION_FIELD,
                    VIDEO_ACTION_FIELD,
                    VIDEO_WRONG_ACTION_FIELD,
                    *VIDEO_GENERATION_FIELDS,
                ],
                "written_by_the_reader": [VIDEO_WRONG_ACTION_FIELD],
            },
            SOURCE_IMAGE_BLOCK: {"fields": list(SOURCE_IMAGE_FIELDS)},
            CLIP_BLOCK: {"fields": list(CLIP_FIELDS)},
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
