"""The spoken vocabulary of the metadata backfill tool.

A recognized phrase labels the clip on screen with a ``video.action`` — the field
Fun Time's metadata filter matches against.  Kept free of the vosk runtime so the
tests import it without an audio backend, the same split Fun Time draws between
its voice_commands and voice_control.

The vosk small model's lexicon has none of the generated-specific compounds
("alpha", "gamma", "delta"...), and a word missing from the lexicon is
silently dropped from a grammar.  Every phrase below is therefore voiced in
words the model knows, and the compound survives only in the action it writes.
"""

from __future__ import annotations

# Spoken act -> the ``video.action`` recorded for it.  The written forms match the
# library's existing Title Case actions ("Alpha", "Beta Gamma") so Fun Time's
# filter finds new clips and old ones with one query.
_ACTS: dict[str, str] = {
    "alpha form": "Alpha",
    "alpha": "Alpha",
    "beta gamma": "Beta Gamma",
    "gamma": "Gamma",
    "zeta": "Zeta",
    "epsilon": "Epsilon",
    "delta": "Delta",
    "delta": "Delta",
}

# Acts the camera words do not apply to — an act named without one.
_UNSCOPED_ACTS: dict[str, str] = {
    "dance": "Dancing",
    "dancing": "Dancing",
    "other": "Other",
}

# Spoken camera word -> the prefix it adds to the action.  "POV" is an initialism,
# and the lexicon's one-word "pov" is a g2p guess at a single syllable — nothing
# there sounds like "pee oh vee".  The letters themselves do: the lexicon prices
# them as their names (P IY, OW, V IY), so spelling the initialism out across three
# words is what actually catches a speaker saying it.  The one-word form stays too,
# for whatever that g2p pronunciation turns out to be; both reach the same action.
_CAMERAS: dict[str, str] = {
    "side": "Side",
    "p o v": "Pov",
    "pov": "Pov",
}

SKIP = "skip"
WEIRD = "weird"
UNDO = "undo"

# Spoken phrase -> control.  "skip" defers the clip to the back of the queue;
# "weird"/"trash" moves it to the weird folder, as Fun Time's "mark as weird" does;
# "undo" takes back the last decision, and keeps stepping back through them.
CONTROLS: dict[str, str] = {
    "skip": SKIP,
    "weird": WEIRD,
    "trash": WEIRD,
    "undo": UNDO,
}

# Spoken phrase -> the ``video.action`` it records.
ACTIONS: dict[str, str] = dict(_UNSCOPED_ACTS)
for _phrase, _action in _ACTS.items():
    ACTIONS[_phrase] = _action
    for _camera_word, _camera in _CAMERAS.items():
        ACTIONS[f"{_camera_word} {_phrase}"] = f"{_camera} {_action}"


def grammar_phrases() -> list[str]:
    """Every phrase the recognizer should listen for, sorted."""
    return sorted({*ACTIONS, *CONTROLS})
