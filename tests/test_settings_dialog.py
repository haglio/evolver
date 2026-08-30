"""Tests for the Settings dialog — where the two saved settings are written
and the Startup shortcut is created or removed."""

from unittest.mock import patch

import pytest

from PyQt6.QtWidgets import QDialog

from gui.settings import EvolverSettings
from gui.settings_dialog import SettingsDialog


@pytest.fixture
def dialog_parts():
    """A dialog over fresh settings, with the disk and Windows kept out of it."""
    settings = EvolverSettings()
    with patch("gui.startup.is_registered", return_value=False), \
         patch.object(EvolverSettings, "save") as save, \
         patch("gui.startup.register_startup") as register, \
         patch("gui.startup.unregister_startup") as unregister:
        dialog = SettingsDialog(settings)
        yield dialog, settings, save, register, unregister


class TestDialogShowsCurrentSettings:

    def test_the_fields_start_at_the_settings_values(self):
        settings = EvolverSettings(interval_minutes=25, enable_toasts=True)
        with patch("gui.startup.is_registered", return_value=True):
            dialog = SettingsDialog(settings)
        assert dialog._interval_spin.value() == 25
        assert dialog._toasts_check.isChecked()
        assert dialog._startup_check.isChecked()

    def test_the_startup_box_reflects_the_real_shortcut(self):
        """The shortcut can be deleted behind the app's back, so the box asks
        the Startup folder — which is the only record of it there is."""
        with patch("gui.startup.is_registered", return_value=False):
            dialog = SettingsDialog(EvolverSettings())
        assert not dialog._startup_check.isChecked()


class TestAccept:

    def test_writes_both_saved_fields_and_saves(self, dialog_parts):
        dialog, settings, save, _, _ = dialog_parts
        dialog._interval_spin.setValue(42)
        dialog._toasts_check.setChecked(True)
        dialog._startup_check.setChecked(False)

        dialog.accept()

        assert settings.interval_minutes == 42
        assert settings.enable_toasts is True
        save.assert_called_once()
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_checking_start_with_windows_registers_the_shortcut(self, dialog_parts):
        dialog, _, _, register, unregister = dialog_parts
        dialog._startup_check.setChecked(True)

        dialog.accept()

        register.assert_called_once_with()
        unregister.assert_not_called()

    def test_unchecking_it_removes_the_shortcut(self, dialog_parts):
        dialog, _, _, register, unregister = dialog_parts
        dialog._startup_check.setChecked(False)

        dialog.accept()

        unregister.assert_called_once_with()
        register.assert_not_called()

    def test_a_failing_shortcut_write_warns_instead_of_crashing(self, dialog_parts):
        """A read-only Startup folder must cost the shortcut and nothing else:
        the settings are already saved, and the dialog still closes accepted."""
        dialog, _, save, register, _ = dialog_parts
        register.side_effect = OSError("Startup folder is read-only")
        dialog._startup_check.setChecked(True)

        with patch("gui.settings_dialog.QMessageBox") as box:
            dialog.accept()

        box.warning.assert_called_once()
        assert "read-only" in box.warning.call_args[0][2]
        save.assert_called_once()
        assert dialog.result() == QDialog.DialogCode.Accepted
