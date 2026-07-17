"""The spoken vocabulary of the metadata backfill tool.

A recognized phrase labels the clip on screen with a ``video.action`` — the field
Fun Time's metadata filter matches against.  Kept free of the vosk runtime so the
tests import it without an audio backend, the same split Fun Time draws between
its voice_commands and voice_control.

The vosk small model's lexicon has none of the generated-specific compounds
("alpha", "gamma", "delta"...), and a word missing from the lexicon is
silently dropped from a grammar.  Every phrase below is therefore voiced in
words the model knows, and the compound survives only in the action it writes.

The typed tables here are the single source of truth for two consumers: the
recognizer grammar (:data:`ACTIONS`, :data:`CONTROLS`) and the window's clickable
reference grid (:func:`scoped_grid`, :func:`unscoped_commands`,
:func:`control_commands`).  An act voiced more than one way — "alpha" and
"alpha form" both record ``Alpha`` — is one ``spoken`` form plus its ``aliases``,
so the grammar hears every form while the grid shows one tile.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Act:
    """An act, its canonical spoken phrase, and any other way it is voiced."""

    spoken: str  # the phrase a click re-emits and the grid tile is built from
    action: str  # the bare Title Case ``video.action`` it records
    aliases: tuple[str, ...] = ()  # extra phrases the recognizer also accepts

    def forms(self) -> tuple[str, ...]:
        return (self.spoken, *self.aliases)


@dataclass(frozen=True)
class _Camera:
    """A camera word: how it is shown, how it is said, and the prefix it adds."""

    label: str  # the grid column header, e.g. "POV"
    spoken: str  # the canonical phrase a click re-emits, e.g. "pov"
    prefix: str  # the prefix it prepends to the action, e.g. "Pov"
    aliases: tuple[str, ...] = ()  # extra phrases the recognizer also accepts

    def forms(self) -> tuple[str, ...]:
        return (self.spoken, *self.aliases)


@dataclass(frozen=True)
class _Control:
    """A non-labelling command — skip, discard, undo, repeat — and how it is voiced."""

    spoken: str
    label: str  # the grid tile text, e.g. "Weird"
    kind: str  # the control constant it maps to (SKIP / WEIRD / UNDO / SAME)
    aliases: tuple[str, ...] = ()

    def forms(self) -> tuple[str, ...]:
        return (self.spoken, *self.aliases)


@dataclass(frozen=True)
class Command:
    """One thing the viewer can invoke: speak its ``phrase`` or click its tile.

    ``label`` is the outcome shown on the tile — the action recorded, or the
    control's name; ``phrase`` is what the recognizer listens for and what a click
    hands to the session, so the mouse and the microphone drive one code path.
    """

    phrase: str
    label: str


# Acts that a camera word may scope.  The written actions match the library's
# existing Title Case ("Alpha", "Beta Gamma") so one Fun Time query reaches new
# clips and old.  "POV" is an initialism: the lexicon's one-word "pov" is a g2p
# guess at a single syllable, while the three letters are priced as their names
# (P IY, OW, V IY), so the spelled-out form is what actually catches a speaker.
_ACTS: tuple[_Act, ...] = (
    _Act("alpha", "Alpha", aliases=("alpha form",)),
    _Act("gamma", "Gamma"),
    _Act("epsilon", "Epsilon"),
    _Act("zeta", "Zeta"),
    _Act("beta gamma", "Beta Gamma"),
    _Act("delta", "Delta"),
    _Act("delta", "Delta"),
)

_CAMERAS: tuple[_Camera, ...] = (
    _Camera(label="Side", spoken="side", prefix="Side"),
    _Camera(label="POV", spoken="pov", prefix="Pov", aliases=("p o v",)),
)

# Acts the camera words do not apply to — an act named on its own.
_UNSCOPED_ACTS: tuple[_Act, ...] = (
    _Act("dance", "Dancing", aliases=("dancing",)),
    _Act("other", "Other"),
)

SKIP = "skip"
WEIRD = "weird"
UNDO = "undo"
SAME = "same"

# "skip" defers the clip to the back of the queue; "weird"/"trash" moves it to the
# weird folder, as Fun Time's "mark as weird" does; "undo" takes back the last
# decision, and keeps stepping back through them; "same" repeats the last act you
# spoke, for a run of clips that share one.
_CONTROLS: tuple[_Control, ...] = (
    _Control("skip", "Skip", SKIP),
    _Control("weird", "Weird", WEIRD, aliases=("trash",)),
    _Control("undo", "Undo", UNDO),
    _Control("same", "Same", SAME),
)

# The grid's columns: the bare act first, then each camera word.
CAMERA_COLUMNS: tuple[str, ...] = ("", *(camera.label for camera in _CAMERAS))


def _build_actions() -> dict[str, str]:
    """Every spoken phrase -> the ``video.action`` it records.

    Each act contributes its bare forms and, for the scopable acts, every
    camera-form × act-form pairing, so the recognizer hears "p o v alpha" and
    "pov alpha form" alike while both record ``Pov Alpha``.
    """
    actions: dict[str, str] = {}
    for act in _ACTS:
        for act_form in act.forms():
            actions[act_form] = act.action
        for camera in _CAMERAS:
            for camera_form in camera.forms():
                for act_form in act.forms():
                    actions[f"{camera_form} {act_form}"] = f"{camera.prefix} {act.action}"
    for act in _UNSCOPED_ACTS:
        for act_form in act.forms():
            actions[act_form] = act.action
    return actions


def _build_controls() -> dict[str, str]:
    return {form: control.kind for control in _CONTROLS for form in control.forms()}

# Spoken phrase -> the ``video.action`` it records.
ACTIONS: dict[str, str] = _build_actions()

# Spoken phrase -> control.
CONTROLS: dict[str, str] = _build_controls()


def scoped_grid() -> list[list[Command]]:
    """A row of :class:`Command` per scopable act, across :data:`CAMERA_COLUMNS`.

    The first cell is the bare act; each later cell prepends one camera word, in
    the column order the header names.  Every cell's ``phrase`` is the canonical
    spoken form, so a click reaches the same action the spoken phrase would.
    """
    rows: list[list[Command]] = []
    for act in _ACTS:
        row = [Command(act.spoken, act.action)]
        for camera in _CAMERAS:
            row.append(Command(f"{camera.spoken} {act.spoken}", f"{camera.prefix} {act.action}"))
        rows.append(row)
    return rows


def unscoped_commands() -> list[Command]:
    """One tile per act that takes no camera word — Dancing, Other."""
    return [Command(act.spoken, act.action) for act in _UNSCOPED_ACTS]


def control_commands() -> list[Command]:
    """One tile per control — Skip, Weird, Undo, Same."""
    return [Command(control.spoken, control.label) for control in _CONTROLS]


def grammar_phrases() -> list[str]:
    """Every phrase the recognizer should listen for, sorted."""
    return sorted({*ACTIONS, *CONTROLS})
