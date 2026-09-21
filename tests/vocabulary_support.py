"""A fabricated vocabulary, in the committed example's placeholder style."""
from __future__ import annotations

from backfill.vocabulary import Act, Camera, Vocabulary

CAMERAS = (Camera("side", "Side"), Camera("xyz", "XYZ", aliases=("x y z",)))


def vocabulary_of(*acts: Act) -> Vocabulary:
    return Vocabulary(acts, CAMERAS)
