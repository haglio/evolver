"""What the backfill tool does with what the family's listener hears: a spoken
phrase is handed to the window.  Hearing itself is voice_core's, the same
listener Fun Time runs.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Collection

from PyQt6.QtCore import QObject, pyqtSignal
from voice_core.commands import CommandRules
from voice_core.listener import (
    SECOND_OPINION_PATIENCE_S,
    CommandListener,
    Engines,
    ListenerEvents,
    ListenerSettings,
    MicrophoneUnavailable,
    RecognizerUnavailable,
)
from voice_core.listening import Heard
from voice_core.whisper_reader import WhisperReader

import config

log = logging.getLogger(__name__)

# A live listener is back within one poll of its microphone plus whatever reading the
# second engine has under way; a wedged one is not something a closing window waits on.
STOP_PATIENCE_S = SECOND_OPINION_PATIENCE_S + 2.0


class VoiceListener(QObject):
    heard = pyqtSignal(str)
    hearing = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, phrases: list[str], parent: QObject | None = None, *,
                 never_repaired: Collection[str] = (),
                 engines: Engines | None = None) -> None:
        super().__init__(parent)
        self._rules = CommandRules(
            phrases=frozenset(phrases),
            never_rescued=frozenset(never_repaired).__contains__,
            confidence_threshold=config.VOICE_CONFIDENCE_THRESHOLD,
        )
        self._engines = engines or Engines(second_opinion=WhisperReader())
        self._listener: CommandListener | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._listener = CommandListener(
            self._rules,
            ListenerSettings(model_name=config.VOICE_MODEL_NAME,
                             device_name=config.VOICE_DEVICE_NAME,
                             sample_rate=config.VOICE_SAMPLE_RATE),
            ListenerEvents(heard=self._on_heard, partial=self.hearing.emit),
            self._engines)
        self._thread = threading.Thread(target=self._run, args=(self._listener,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        thread, self._thread = self._thread, None
        if listener is not None:
            listener.stop()
        if thread is not None:
            thread.join(timeout=STOP_PATIENCE_S)

    def _run(self, listener: CommandListener) -> None:
        try:
            listener.run()
        except RecognizerUnavailable as exc:
            self._give_up("Voice listener crashed", exc)
        except MicrophoneUnavailable as exc:
            self._give_up("Microphone could not be opened", exc)
        except Exception as exc:
            self._give_up("Voice listener stopped listening", exc)

    def _give_up(self, what_happened: str, exc: Exception) -> None:
        log.exception(what_happened)
        self.failed.emit(str(exc) or type(exc).__name__)

    def _on_heard(self, heard: Heard) -> None:
        if heard.recognition.phrase:
            self.heard.emit(heard.recognition.phrase)
