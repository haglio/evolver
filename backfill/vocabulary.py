# vosk's lexicon lacks most compounds and silently drops unknown words from a grammar, so phrases are voiced in words it knows.

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from content_overlay import load_content


@dataclass(frozen=True)
class _Voiced:
    spoken: str
    aliases: tuple[str, ...] = field(default=(), kw_only=True)

    def forms(self) -> tuple[str, ...]:
        return (self.spoken, *self.aliases)


@dataclass(frozen=True)
class Act(_Voiced):
    action: str


@dataclass(frozen=True)
class Camera(_Voiced):
    prefix: str


@dataclass(frozen=True)
class _Control(_Voiced):
    label: str
    kind: str


@dataclass(frozen=True)
class Command:
    phrase: str
    label: str


SKIP = "skip"
TRASH = "trash"
UNDO = "undo"
SAME = "same"

_CONTROLS: tuple[_Control, ...] = (
    _Control("skip", "Skip", SKIP),
    _Control("trash", "Trash", TRASH),
    _Control("undo", "Undo", UNDO),
    _Control("same", "Same", SAME),
)


class Vocabulary:
    def __init__(self, acts: Iterable[Act], cameras: Iterable[Camera]) -> None:
        self.acts = tuple(acts)
        self.cameras = tuple(cameras)
        self.actions: dict[str, str] = {
            f"{camera_form} {act_form}": f"{camera.prefix} {act.action}"
            for act in self.acts
            for camera in self.cameras
            for camera_form in camera.forms()
            for act_form in act.forms()
        }
        self.controls: dict[str, str] = {
            form: control.kind for control in _CONTROLS for form in control.forms()
        }

    def scoped_grid(self) -> list[list[Command]]:
        return [
            [
                Command(f"{camera.spoken} {act.spoken}", f"{camera.prefix} {act.action}")
                for camera in self.cameras
            ]
            for act in self.acts
        ]

    def control_commands(self) -> list[Command]:
        return [Command(control.spoken, control.label) for control in _CONTROLS]

    def grammar_phrases(self) -> list[str]:
        return sorted({*self.actions, *self.controls})

    def discarding_phrases(self) -> set[str]:
        return {phrase for phrase, kind in self.controls.items() if kind == TRASH}


def _aliases(entry: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(entry.get("aliases", ()))


def load_vocabulary() -> Vocabulary:
    content = load_content()
    return Vocabulary(
        (Act(entry["spoken"], entry["action"], aliases=_aliases(entry))
         for entry in content["acts"]),
        (Camera(entry["spoken"], entry["prefix"], aliases=_aliases(entry))
         for entry in content["cameras"]),
    )
