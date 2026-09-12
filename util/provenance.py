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


def reconstructed(app: str | None, *, recipe: str | None = None,
                  recipe_version: str | None = None) -> dict:
    return {"schema": SCHEMA, "app": app, "app_commit": None, "app_dirty": None,
            "recipe": recipe, "recipe_version": recipe_version, "stamped_at": None}
