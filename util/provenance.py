"""What made a video or a funscript, kept on the file's own record, one stamp per act.

A stamp's seven keys are :mod:`app_support.provenance`'s, and so is taking one.
What is this app's is where the stamps are kept and the acts they are filed
under -- and the stamp for an act nobody recorded at the time, which knows only
what could still be looked up afterwards.
"""
from __future__ import annotations

from app_support.provenance import SCHEMA

#: Where the stamps sit on a record: ``payload["provenance"][<act>]``.
BLOCK = "provenance"

#: The acts a stamp is filed under.
GENERATION = "generation"


def carried_forward(earlier: dict, later: dict) -> dict:
    """*later*, holding every stamp *earlier* did beside its own -- a copy.

    Where both record the same act, *later*'s stands: it is the newer word on
    what made the file.
    """
    stamps = {**_stamps_of(earlier), **_stamps_of(later)}
    return {**later, BLOCK: stamps} if stamps else later


def _stamps_of(payload: dict) -> dict:
    stamps = payload.get(BLOCK)
    return stamps if isinstance(stamps, dict) else {}


def reconstructed(app: str | None, *, recipe: str | None = None,
                  recipe_version: str | None = None) -> dict:
    return {"schema": SCHEMA, "app": app, "app_commit": None, "app_dirty": None,
            "recipe": recipe, "recipe_version": recipe_version, "stamped_at": None}
