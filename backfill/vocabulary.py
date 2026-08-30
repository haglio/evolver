"""The spoken vocabulary of the metadata backfill tool.

A recognized phrase labels the clip on screen with a ``video.action`` — the field
Fun Time's metadata filter matches against.  Kept free of the vosk runtime so the
tests import it without an audio backend, the same split Fun Time draws between
its voice_commands and voice_control.

The vosk small model's lexicon has none of the domain-specific compounds the
library records as actions, and a word missing from the lexicon is silently
dropped from a grammar.  Every phrase is therefore voiced in words the model
knows, and the compound survives only in the action it writes.

The act table itself is content, not logic, so it lives in a JSON overlay
(``content.local.json``, git-ignored) with a committed ``content.example.json``
placeholder; the grammar and the grid behave the same whichever is loaded.

The typed tables here are the single source of truth for two consumers: the
recognizer grammar (:data:`ACTIONS`, :data:`CONTROLS`) and the window's clickable
reference grid (:func:`scoped_grid`, :func:`control_commands`).  An act voiced
more than one way is one ``spoken`` form plus its ``aliases``, so the grammar
hears every form while the grid shows one tile.  Every act is scoped by a camera word: a clip is always
tagged Side or POV, never bare.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from content import EXAMPLE_CONTENT, LOCAL_CONTENT, load_content


@dataclass(frozen=True)
class _Act:
    """An act, its canonical spoken phrase, and any other way it is voiced."""

    spoken: str  # the phrase a click re-emits and the grid tile is built from
    action: str  # the Title Case act stem a camera word prefixes
    aliases: tuple[str, ...] = ()  # extra phrases the recognizer also accepts

    def forms(self) -> tuple[str, ...]:
        return (self.spoken, *self.aliases)


@dataclass(frozen=True)
class _Camera:
    """A camera word: how it is said, and the prefix it adds."""

    spoken: str  # the canonical phrase a click re-emits, e.g. "pov"
    prefix: str  # the prefix it prepends to the action, and the grid's column header
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


def load_acts(
    local_path: Path = LOCAL_CONTENT,
    example_path: Path = EXAMPLE_CONTENT,
) -> tuple[_Act, ...]:
    """Every act, from the content overlay — the local copy, else the example.

    Each is scoped by a camera word so none stands bare, and the written actions
    keep the library's existing Title Case, so one Fun Time query reaches new
    clips and old.
    """
    data = load_content(local_path, example_path)
    return tuple(
        _Act(
            spoken=entry["spoken"],
            action=entry["action"],
            aliases=tuple(entry.get("aliases", ())),
        )
        for entry in data["acts"]
    )


_ACTS: tuple[_Act, ...] = load_acts()

# "POV" is an initialism: the lexicon's one-word "pov" is a g2p guess at a single
# syllable, while the three letters are priced as their names (P IY, OW, V IY), so
# the spelled-out form is what actually catches a speaker.
_CAMERAS: tuple[_Camera, ...] = (
    _Camera(spoken="side", prefix="Side"),
    _Camera(spoken="pov", prefix="POV", aliases=("p o v",)),
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


def _build_actions() -> dict[str, str]:
    """Every spoken phrase -> the ``video.action`` it records.

    Each act is scoped by a camera word; the recognizer hears every camera-form ×
    act-form pairing — "p o v alpha" and "pov alpha form" alike record
    ``POV Alpha`` — and no bare, camera-less form is offered.
    """
    actions: dict[str, str] = {}
    for act in _ACTS:
        for camera in _CAMERAS:
            for camera_form in camera.forms():
                for act_form in act.forms():
                    actions[f"{camera_form} {act_form}"] = f"{camera.prefix} {act.action}"
    return actions


def _build_controls() -> dict[str, str]:
    return {form: control.kind for control in _CONTROLS for form in control.forms()}

ACTIONS: dict[str, str] = _build_actions()
CONTROLS: dict[str, str] = _build_controls()


def scoped_grid() -> list[list[Command]]:
    """A row of :class:`Command` per act, one cell per camera word.

    Each cell prepends a camera word, one column per camera in the order
    :data:`_CAMERAS` lists them; there is no bare column, so an act is only ever
    Side or POV.  Every cell's ``phrase`` is the canonical spoken form, so a
    click reaches the same action the spoken phrase would.
    """
    rows: list[list[Command]] = []
    for act in _ACTS:
        rows.append(
            [
                Command(f"{camera.spoken} {act.spoken}", f"{camera.prefix} {act.action}")
                for camera in _CAMERAS
            ]
        )
    return rows


def control_commands() -> list[Command]:
    """One tile per control — Skip, Weird, Undo, Same."""
    return [Command(control.spoken, control.label) for control in _CONTROLS]


def grammar_phrases() -> list[str]:
    """Every phrase the recognizer should listen for, sorted."""
    return sorted({*ACTIONS, *CONTROLS})
