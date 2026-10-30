"""What made a video or a funscript, kept on the file's own record, one stamp per act.

A stamp's seven keys are :mod:`app_support.provenance`'s, and so is taking one.
What is this app's is where the stamps are kept and the acts they are filed
under -- and the stamp for an act nobody recorded at the time, which knows only
what could still be looked up afterwards.
"""
from __future__ import annotations

import app_support.provenance
from app_support.provenance import METHOD, METHOD_VERSION

#: Where the stamps sit on a record: ``payload["provenance"][<act>]``.
BLOCK = "provenance"

#: The acts a stamp is filed under.
GENERATION = "generation"
UPSCALE = "upscale"
UPSCALE_NON_AI = "upscale_non_ai"
CLIP_SCRIPTS = "clip_scripts"
SCENE_SCRIPTS = "scene_scripts"

# The checkout is read here, as this module is imported with the rest of the
# app, rather than at the first stamp: the tray runs for days on the code it
# loaded while the checkout under it moves on, and a stamp taken a day later
# would otherwise name a commit that is not what is running.
app_support.provenance.stamp("evolver", anchor=__file__)


def by_evolver(*, method: str | None = None, method_version: str | None = None) -> dict:
    """The stamp for something this app is writing now."""
    return app_support.provenance.stamp(
        "evolver", anchor=__file__, method=method, method_version=method_version)


def recorded(payload: dict, act: str, stamp: dict) -> dict:
    """*payload* with *stamp* filed under *act*, beside its other stamps -- a copy."""
    return {**payload, BLOCK: {**stamps_of(payload), act: stamp}}


def without(payload: dict, act: str) -> dict:
    """*payload* with no stamp filed under *act* -- a copy."""
    return {**payload, BLOCK: {kept: stamp for kept, stamp in stamps_of(payload).items()
                               if kept != act}}


def carried_forward(earlier: dict, later: dict) -> dict:
    """*later*, holding every stamp *earlier* did beside its own -- a copy.

    Where both record the same act, *later*'s stands: it is the newer word on
    what made the file.
    """
    stamps = {**stamps_of(earlier), **stamps_of(later)}
    return {**later, BLOCK: stamps} if stamps else later


def stamps_of(payload: dict) -> dict:
    """The stamps *payload* records, by act -- none when it records none."""
    stamps = payload.get(BLOCK)
    return stamps if isinstance(stamps, dict) else {}


def reconstructed(app: str | None, *, method: str | None = None,
                  method_version: str | None = None) -> dict:
    return {"schema": app_support.provenance.SCHEMA, "app": app,
            "app_commit": None, "app_dirty": None,
            METHOD: method, METHOD_VERSION: method_version, "stamped_at": None}
