import json
import unittest

from tests.temp_helpers import workspace_temp_dir

from gui.settings import EvolverSettings


class TestEvolverSettings(unittest.TestCase):

    def test_defaults(self):
        s = EvolverSettings()
        self.assertEqual(s.interval_minutes, 10)
        self.assertFalse(s.enable_toasts)

    def test_the_file_holds_only_settings_something_reads_back(self):
        """A key written every save and never read is not configuration."""
        self.assertEqual(
            set(EvolverSettings.__dataclass_fields__),
            {"interval_minutes", "enable_toasts", "nonai_upscale_enabled"},
        )

    def test_save_and_load_round_trip(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            s = EvolverSettings(interval_minutes=5, enable_toasts=True)
            s.save(path)

            loaded = EvolverSettings.load(path)
            self.assertEqual(loaded.interval_minutes, 5)
            self.assertTrue(loaded.enable_toasts)

    def test_a_file_still_carrying_start_with_windows_loads(self):
        """The key was written for years; a hand-edited or old file keeps it."""
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            path.write_text(json.dumps({"interval_minutes": 7, "start_with_windows": True}))

            self.assertEqual(EvolverSettings.load(path).interval_minutes, 7)

    def test_load_returns_defaults_for_missing_file(self):
        s = EvolverSettings.load(path=None)
        # Will try config.GUI_SETTINGS_FILE which won't exist in test env
        self.assertEqual(s.interval_minutes, 10)

    def test_load_ignores_unknown_fields(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            path.write_text(json.dumps({"interval_minutes": 7, "unknown_field": "hi"}))
            loaded = EvolverSettings.load(path)
            self.assertEqual(loaded.interval_minutes, 7)

    def test_load_returns_defaults_for_corrupt_file(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            path.write_text("not json!!!")
            loaded = EvolverSettings.load(path)
            self.assertEqual(loaded.interval_minutes, 10)

    def test_enable_toasts_defaults_to_false(self):
        s = EvolverSettings()
        self.assertFalse(s.enable_toasts)

    def test_nonai_upscale_defaults_to_off(self):
        s = EvolverSettings()
        self.assertFalse(s.nonai_upscale_enabled)

    def test_nonai_upscale_round_trip(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            s = EvolverSettings(nonai_upscale_enabled=True)
            s.save(path)

            loaded = EvolverSettings.load(path)
            self.assertTrue(loaded.nonai_upscale_enabled)

    def test_enable_toasts_round_trip(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            s = EvolverSettings(enable_toasts=True)
            s.save(path)

            loaded = EvolverSettings.load(path)
            self.assertTrue(loaded.enable_toasts)


if __name__ == "__main__":
    unittest.main()
