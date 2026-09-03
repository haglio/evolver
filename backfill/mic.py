"""Choosing which microphone the backfill recognizer listens on.

Windows often makes a dead virtual input the system default — a VR headset's silent
mic (a Pimax update is enough to repoint it), "Sound Mapper", and the like — which
hands back pure silence, so vosk hears nothing and the tool just sits there. Opening
``device=None`` walks straight into that. :func:`resolve_input_device` avoids it by
probing the real inputs and taking the liveliest, or by honoring an explicit name
override.

The pure selection lives in :func:`choose_input_device`, which takes the probe as an
injected callable so it is tested without a microphone; only :func:`probe_input_device`
and :func:`resolve_input_device` touch the audio backend, and they import it lazily so
this module stays importable without one — the same split the rest of ``backfill`` draws.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

import config

log = logging.getLogger(__name__)

_PROBE_SECONDS = 0.4


@dataclass(frozen=True)
class ChosenInput:
    """Which device was picked. The name is for the log line that says so."""

    index: int
    name: str


def choose_input_device(
    devices: list[dict],
    probe: Callable[[int], float],
    *,
    override: str | None = None,
    hostapi: int | None = None,
) -> ChosenInput | None:
    """Pick an input device from a ``sounddevice.query_devices()`` list.

    Override else liveliest, and None when there is no input device to probe at
    all. What each of those two means is in the function that does it.
    """
    inputs = _inputs_on(devices, hostapi)
    return _matching_override(inputs, override) or _liveliest(inputs, probe)


def _inputs_on(devices: list[dict], hostapi: int | None) -> list[tuple[int, dict]]:
    """The devices that can record, on *hostapi* when one is named.

    On Windows the same mic is listed under several host APIs and some (WDM-KS)
    cannot be opened for blocking reads, so selection sticks to the API the OS
    default already uses.
    """
    return [
        (index, device)
        for index, device in enumerate(devices)
        if device.get("max_input_channels", 0) > 0
        and (hostapi is None or device.get("hostapi") == hostapi)
    ]


def _matching_override(inputs: list[tuple[int, dict]],
                       override: str | None) -> ChosenInput | None:
    """The first input whose name contains *override*, unprobed.

    An explicit choice never listens to anything: the user has said which mic,
    and probing it could only overrule them.
    """
    want = (override or "").strip().lower()
    if not want:
        return None
    for index, device in inputs:
        if want in device["name"].lower():
            return ChosenInput(index, device["name"])
    return None


def _liveliest(inputs: list[tuple[int, dict]],
               probe: Callable[[int], float]) -> ChosenInput | None:
    """The input hearing the most, measured by ``probe(index) -> rms``.

    Liveliest rather than "above some level": a real mic's self-noise always
    beats a disconnected virtual device's ~0, so this passes over a dead
    default even in a silent room, where an absolute threshold would find
    nothing and fall back to that very dead default.
    """
    best: ChosenInput | None = None
    best_level: float | None = None
    seen: set[str] = set()
    for index, device in inputs:
        if device["name"] in seen:
            continue  # same physical mic, different host API — probe it once
        seen.add(device["name"])
        try:
            level = probe(index)
        except Exception:
            # A device that consistently refuses to open is why nothing is
            # heard; without a line here there is nothing anywhere to say so.
            log.debug("Input device %d could not be probed.", index, exc_info=True)
            continue
        if level is None or not math.isfinite(level):
            continue
        if best_level is None or level > best_level:
            best, best_level = ChosenInput(index, device["name"]), level
    return best


def probe_input_device(index: int) -> float:
    """Measure device *index*'s live RMS by briefly recording int16 mono from it.

    Real hardware; :func:`choose_input_device` takes this as an injected callable.
    Records at the device's own default sample rate (so a device that does not
    support 16 kHz still opens) and computes RMS from the raw int16 frames with the
    stdlib ``array`` — no numpy, matching the recognizer's own RawInputStream path.
    """
    import array
    import queue as _queue

    import sounddevice

    sample_rate = int(sounddevice.query_devices(index)["default_samplerate"])
    wanted_bytes = int(_PROBE_SECONDS * sample_rate) * 2  # int16 → 2 bytes per sample
    collected = bytearray()
    frames: _queue.Queue[bytes] = _queue.Queue()

    def on_audio(indata, _frames, _time, _status):
        frames.put(bytes(indata))

    with sounddevice.RawInputStream(
        samplerate=sample_rate,
        blocksize=0,
        dtype="int16",
        channels=1,
        device=index,
        callback=on_audio,
    ):
        while len(collected) < wanted_bytes:
            try:
                collected += frames.get(timeout=1.0)
            except _queue.Empty:
                break
    samples = array.array("h")
    samples.frombytes(bytes(collected[: len(collected) // 2 * 2]))
    if not samples:
        return 0.0
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


def resolve_input_device() -> int | None:
    """The input device index the recognizer should open.

    Honors :data:`config.VOICE_DEVICE_NAME` as a name-substring pin; otherwise takes
    the liveliest live input on the OS default's host API, so a dead default (the VR
    mic a Pimax update repointed to) is passed over instead of feeding vosk silence.
    Returns None only when nothing could be probed, leaving the stream to fall back
    to the system default.
    """
    import sounddevice

    default_input = sounddevice.default.device[0]
    hostapi = None
    if default_input is not None and default_input >= 0:
        hostapi = sounddevice.query_devices(default_input)["hostapi"]
    chosen = choose_input_device(
        sounddevice.query_devices(),
        probe_input_device,
        override=config.VOICE_DEVICE_NAME,
        hostapi=hostapi,
    )
    if chosen is None:
        log.warning("No usable input device found; falling back to the system default")
        return None
    log.info("Listening on input device [%d] %s", chosen.index, chosen.name)
    return chosen.index
