"""What the backfill tool does with what the family's listener hears: a spoken
phrase is handed to the window.  Hearing itself is voice_core's, the same
listener Fun Time runs.
"""

from __future__ import annotations

import logging
from collections.abc import Collection

from PyQt6.QtCore import QObject, pyqtSignal
from voice_core.commands import CommandRules
from voice_core.listener import (
    CommandListener,
    Engines,
    ListenerEvents,
    ListenerSettings,
    MicrophoneUnavailable,
    RecognizerUnavailable,
)
from voice_core.listening import Heard
from voice_core.listening_thread import ListeningThread
from voice_core.whisper_reader import WhisperReader

import config

log = logging.getLogger(__name__)


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
        self._thread = ListeningThread(self._listener, failed=self._give_up)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._thread.stop()

    def _listener(self) -> CommandListener:
        return CommandListener(
            self._rules,
            ListenerSettings(model_name=config.VOICE_MODEL_NAME,
                             device_name=config.VOICE_DEVICE_NAME,
                             sample_rate=config.VOICE_SAMPLE_RATE),
            ListenerEvents(heard=self._on_heard, partial=self.hearing.emit),
            self._engines)

    def _give_up(self, exc: Exception) -> None:
        what_happened = {
            RecognizerUnavailable: "Voice listener crashed",
            MicrophoneUnavailable: "Microphone could not be opened",
        }.get(type(exc), "Voice listener stopped listening")
        log.error(what_happened, exc_info=exc)
        self.failed.emit(str(exc) or type(exc).__name__)

    def _on_heard(self, heard: Heard) -> None:
        if heard.recognition.phrase:
            self.heard.emit(heard.recognition.phrase)
