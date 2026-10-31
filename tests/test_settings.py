from __future__ import annotations

import json
import unittest

from gui.settings import EvolverSettings
from tests.temp_helpers import workspace_temp_dir


class TestEvolverSettings(unittest.TestCase):

    def test_defaults(self):
        s = EvolverSettings()
        assert s.interval_minutes == 10
        assert not s.enable_toasts

    def test_the_file_holds_only_settings_something_reads_back(self):
        """A key written every save and never read is not configuration."""
        assert set(EvolverSettings.__dataclass_fields__) == {"interval_minutes", "enable_toasts", "nonai_upscale_enabled"}

    def test_save_and_load_round_trip(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            s = EvolverSettings(interval_minutes=5, enable_toasts=True)
            s.save(path)

            loaded = EvolverSettings.load(path)
            assert loaded.interval_minutes == 5
            assert loaded.enable_toasts

    def test_a_hand_edited_interval_below_one_loads_as_one(self):
        """The spinner is clamped to 1..120, but the file is plain JSON in the
        project folder and nothing stopped a 0 from reaching the scheduler's
        clock-alignment arithmetic, which divides by it."""
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            path.write_text(json.dumps({"interval_minutes": 0}))
            assert EvolverSettings.load(path).interval_minutes == 1

            path.write_text(json.dumps({"interval_minutes": -5}))
            assert EvolverSettings.load(path).interval_minutes == 1

    def test_a_file_still_carrying_start_with_windows_loads(self):
        """The key was written for years; a hand-edited or old file keeps it."""
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            path.write_text(json.dumps({"interval_minutes": 7, "start_with_windows": True}))

            assert EvolverSettings.load(path).interval_minutes == 7

    def test_settings_that_were_never_saved_come_up_at_the_defaults(self):
        s = EvolverSettings.load(path=None)
        # Will try config.GUI_SETTINGS_FILE which won't exist in test env
        assert s.interval_minutes == 10

    def test_load_ignores_unknown_fields(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            path.write_text(json.dumps({"interval_minutes": 7, "unknown_field": "hi"}))
            loaded = EvolverSettings.load(path)
            assert loaded.interval_minutes == 7

    def test_settings_too_damaged_to_parse_come_up_at_the_defaults(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            path.write_text("not json!!!")
            loaded = EvolverSettings.load(path)
            assert loaded.interval_minutes == 10

    def test_a_corrupt_file_says_so_before_the_defaults_overwrite_it(self):
        """Silently resetting is how one malformed byte turns into "my interval
        went back to ten and I do not know why" -- and the next save writes the
        evidence away."""
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            path.write_text("not json!!!")

            with self.assertLogs("gui.settings", level="WARNING") as caught:
                EvolverSettings.load(path)

            assert any(str(path) in record.getMessage() for record in caught.records)

    def test_enable_toasts_defaults_to_false(self):
        s = EvolverSettings()
        assert not s.enable_toasts

    def test_nonai_upscale_defaults_to_off(self):
        s = EvolverSettings()
        assert not s.nonai_upscale_enabled

    def test_nonai_upscale_round_trip(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            s = EvolverSettings(nonai_upscale_enabled=True)
            s.save(path)

            loaded = EvolverSettings.load(path)
            assert loaded.nonai_upscale_enabled

    def test_enable_toasts_round_trip(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            s = EvolverSettings(enable_toasts=True)
            s.save(path)

            loaded = EvolverSettings.load(path)
            assert loaded.enable_toasts


if __name__ == "__main__":
    unittest.main()
