"""The shape of a library video's record, for the apps that read one.

Every video in the library may have a JSON record beside the tree, and this
repo is the one that writes most of it.  Fun Time reads that record on every
clip it shows -- the act, the kind, the title, the prompt a generation came
from -- and writes one field back into it, the act a viewer has struck out as
wrong.  Neither repo can import the other, so both spelled every block and
field name for itself, and nothing compared the two: a key renamed here left
the reader quietly answering "nothing recorded", with both suites green (audit
cross/boundaries/cross/003, the fun_time-evolver cycle).

What a reader may rely on is declared here and published in the document
:mod:`util.contract` writes.  The names come from the modules that actually
write them wherever there is one, so the document says what the code does
rather than what somebody once wrote down.

A field NOT here is one this repo does not promise: it may be written, and a
reader may still take it, but it can move without warning.
"""
from __future__ import annotations

from util import video_type, watch
from util.sidecar import WRONG_ACTION_FIELD

#: The block holding what a video is and what it was made from.
VIDEO_BLOCK = video_type.BLOCK

#: Inside it: the kind of video (:data:`VIDEO_KINDS`), its running time, the act
#: it depicts, and -- written by Fun Time rather than here -- the act a viewer
#: struck out as wrong, which is what tells the backfill tool this clip was
#: REJECTED rather than never labeled.
VIDEO_TYPE_FIELD = video_type.FIELD
VIDEO_DURATION_FIELD = video_type.DURATION_FIELD
VIDEO_ACTION_FIELD = "action"
VIDEO_WRONG_ACTION_FIELD = WRONG_ACTION_FIELD

#: Every kind a video is recorded as, which a reader branching on one has to
#: know the whole of.
VIDEO_KINDS = video_type.TYPES

#: The rest of the video block: what a generation was made from, as this repo
#: reads it out of a gallery row or scrapes it off a provider's page.  A record
#: written before something was known simply lacks that field.
VIDEO_GENERATION_FIELDS = (
    "prompt", "model", "resolution", "aspect_ratio", "quality", "style",
    "seed", "created",
)

#: The block describing the still a video was animated from, when it was.  Its
#: presence is what says the video is image-to-video at all.
SOURCE_IMAGE_BLOCK = "source_image"
SOURCE_IMAGE_FIELDS = (
    "positive_prompt", "negative_prompt", "model", "action", "resolution",
    "aspect_ratio", "quality", "style", "creativity", "seed", "created",
)

#: The block saying a video was carved out of a longer one: who is in it and
#: what it came from (written by the app that cuts them), and the scene this
#: repo matched it back to.
CLIP_BLOCK = "clip"
CLIP_FIELDS = ("performer", "source", "full_video", "scene_offset")

#: The block tying a video to the other encodings of the same footage.
VERSION_BLOCK = "version"
VERSION_GROUP_FIELD = "group"

#: The block summing every app's viewing of a video, and the playback weight
#: that sum earns -- the number a shuffled playlist draws by.
WATCH_BLOCK = watch.BLOCK
WATCH_COUNT_FIELDS = watch.COUNT_FIELDS
WATCH_WEIGHT_FIELD = "weight"

#: At the top level rather than in a block: what to call the video, and whether
#: it is a favorite.
TITLE_KEY = "title"
FAVORITE_KEY = watch.FAVORITE_FIELD


def declaration() -> dict:
    """The record's shape, as a reader of one reads it."""
    return {
        "blocks": {
            VIDEO_BLOCK: {
                "fields": [
                    VIDEO_TYPE_FIELD,
                    VIDEO_DURATION_FIELD,
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
        "top_level_keys": [TITLE_KEY, FAVORITE_KEY],
        "video_kinds": list(VIDEO_KINDS),
    }
