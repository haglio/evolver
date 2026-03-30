"""Settings dialog for the tray application."""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from gui.settings import EvolverSettings
from gui import startup

log = logging.getLogger(__name__)


class SettingsDialog(QDialog):

    def __init__(self, settings: EvolverSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evolver Settings")
        self._settings = settings

        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 120)
        self._interval_spin.setSuffix(" minutes")
        self._interval_spin.setValue(settings.interval_minutes)
        form.addRow("Run interval:", self._interval_spin)

        self._startup_check = QCheckBox("Start with Windows")
        self._startup_check.setChecked(startup.is_registered())
        form.addRow(self._startup_check)

        self._toasts_check = QCheckBox("Enable toast notifications")
        self._toasts_check.setChecked(settings.enable_toasts)
        form.addRow(self._toasts_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        self._settings.interval_minutes = self._interval_spin.value()
        self._settings.start_with_windows = self._startup_check.isChecked()
        self._settings.enable_toasts = self._toasts_check.isChecked()
        self._settings.save()

        try:
            if self._settings.start_with_windows:
                startup.register_startup()
            else:
                startup.unregister_startup()
        except Exception as exc:
            log.exception("Failed to update startup registration")
            QMessageBox.warning(self, "Startup Registration", f"Could not update startup shortcut:\n{exc}")

        super().accept()

    @property
    def settings(self) -> EvolverSettings:
        return self._settings
