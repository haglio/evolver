"""Always-on voice recognition for the backfill tool, over a restricted grammar.

Fun Time drives the same offline recognizer (vosk) from a phrase list and routes
what it hears into a command file; here the heard phrase is emitted straight to
the window.  vosk and sounddevice are imported inside the listening thread, so
the pure grammar and parsing below stay importable without an audio backend.
"""

from __future__ import annotations

import json
import logging
import queue
import threading

from PyQt6.QtCore import QObject, pyqtSignal

import config
from backfill.mic import resolve_input_device

log = logging.getLogger(__name__)

_UNKNOWN = "[unk]"
_BLOCK_SIZE = 8000

# How long stop() waits for the listening thread. The loop polls the stop event
# every 0.5 s through the audio queue's timeout, so this is four chances to
# notice -- long enough that a live thread always makes it, short enough that a
# wedged one does not hold a closing window.
_STOP_TIMEOUT_SECONDS = 2.0


def build_grammar(phrases: list[str]) -> str:
    """The vosk grammar restricting the recognizer to *phrases*.

    ``[unk]`` gives everything else somewhere to land, so an off-script utterance
    is reported as unknown rather than forced onto the nearest phrase.
    """
    return json.dumps([*sorted(phrases), _UNKNOWN])


def partial_text(raw_partial: str) -> str:
    """The live, still-forming hypothesis a vosk partial carries.

    Empty until the recognizer has settled on grammar words, so the window's
    "hearing" line stays blank while nothing on-script is being said — which is
    itself the signal that an off-grammar word ("bypass", "next") is not landing.
    """
    try:
        payload = json.loads(raw_partial)
    except json.JSONDecodeError:
        return ""
    text = str(payload.get("partial", "")).strip()
    return "" if text == _UNKNOWN else text


def recognized_phrase(raw_result: str, *, threshold: float) -> str | None:
    """The phrase a vosk result carries, or None if there is nothing to act on.

    Silence, the unknown token, and anything whose mean per-word confidence falls
    below *threshold* are all rejected.  Grammar mode routinely reports no
    confidences at all, and a phrase that arrives without them is trusted.
    """
    try:
        payload = json.loads(raw_result)
    except json.JSONDecodeError:
        return None
    text = str(payload.get("text", "")).strip()
    if not text or text == _UNKNOWN:
        return None
    words = payload.get("result")
    if words:
        mean_confidence = sum(word.get("conf", 0) for word in words) / len(words)
        if mean_confidence < threshold:
            return None
    return text


class VoiceListener(QObject):
    """Listens on the microphone, emitting both the live guess and each settled phrase.

    ``hearing`` carries the still-forming hypothesis so the window can show what the
    recognizer currently thinks it is being told; ``heard`` carries a phrase from the
    grammar once the recognizer has committed to it.
    """

    heard = pyqtSignal(str)
    hearing = pyqtSignal(str)
    # The recognizer stopped for good. Without it the window kept showing its
    # command grid with nothing saying the microphone path had gone, so a user
    # was left clicking tiles wondering why speech had stopped working.
    failed = pyqtSignal(str)

    def __init__(self, phrases: list[str], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._phrases = phrases
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the thread to finish, and wait for it to.

        Waiting matters twice. The loop is inside a PortAudio stream's context,
        so returning without a join lets the interpreter tear down while a C
        callback thread is still live in it. And clearing the reference is what
        makes a stopped listener startable again -- start()'s guard is on this
        attribute, so leaving it set made stopping permanent.

        Bounded: the loop polls the stop event every 0.5 s through the queue's
        timeout, so a live one returns promptly and a wedged one is not
        something a closing window should hang on.
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=_STOP_TIMEOUT_SECONDS)

    def _run(self) -> None:
        audio: queue.Queue[bytes] = queue.Queue()

        def on_audio(indata, _frames, _time, status):
            if status:
                log.debug("audio status: %s", status)
            audio.put(bytes(indata))

        try:
            import sounddevice
            import vosk

            model = vosk.Model(model_name=config.VOICE_MODEL_NAME)
            recognizer = vosk.KaldiRecognizer(
                model, config.VOICE_SAMPLE_RATE, build_grammar(self._phrases)
            )
            # Pick a live mic, not the (possibly dead) system default — resolve logs
            # which device it settled on.
            device = resolve_input_device()
            log.info("Listening (model=%s, device=%s)", config.VOICE_MODEL_NAME, device)

            with sounddevice.RawInputStream(
                samplerate=config.VOICE_SAMPLE_RATE,
                blocksize=_BLOCK_SIZE,
                dtype="int16",
                channels=1,
                device=device,
                callback=on_audio,
            ):
                last_partial = ""
                while not self._stop.is_set():
                    try:
                        block = audio.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if not recognizer.AcceptWaveform(block):
                        partial = partial_text(recognizer.PartialResult())
                        if partial != last_partial:
                            last_partial = partial
                            self.hearing.emit(partial)
                        continue
                    # The utterance ended: whatever the live guess was, it is stale now.
                    if last_partial:
                        last_partial = ""
                        self.hearing.emit("")
                    phrase = recognized_phrase(
                        recognizer.Result(), threshold=config.VOICE_CONFIDENCE_THRESHOLD
                    )
                    if phrase:
                        log.info("Heard: %s", phrase)
                        self.heard.emit(phrase)
        except Exception as exc:
            log.exception("Voice listener crashed")
            self.failed.emit(str(exc) or type(exc).__name__)
