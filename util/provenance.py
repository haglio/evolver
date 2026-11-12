from __future__ import annotations

import app_support.provenance
from app_support.provenance import METHOD, METHOD_VERSION

BLOCK = "provenance"

UPSCALE = "upscale"
UPSCALE_NON_AI = "upscale_non_ai"
CLIP_SCRIPTS = "clip_scripts"
SCENE_SCRIPTS = "scene_scripts"


def _pin_every_stamp_to_the_commit_loaded_now() -> None:
    app_support.provenance.stamp("evolver", anchor=__file__)


_pin_every_stamp_to_the_commit_loaded_now()


def by_evolver(*, method: str | None = None, method_version: str | None = None) -> dict:
    return app_support.provenance.stamp(
        "evolver", anchor=__file__, method=method, method_version=method_version)


def recorded(payload: dict, act: str, stamp: dict) -> dict:
    return {**payload, BLOCK: {**stamps_of(payload), act: stamp}}


def stamps_of(payload: dict) -> dict:
    stamps = payload.get(BLOCK)
    return stamps if isinstance(stamps, dict) else {}


def reconstructed(app: str | None, *, method: str | None = None,
                  method_version: str | None = None) -> dict:
    return {"schema": app_support.provenance.SCHEMA, "app": app,
            "app_commit": None, "app_dirty": None,
            METHOD: method, METHOD_VERSION: method_version, "stamped_at": None}
