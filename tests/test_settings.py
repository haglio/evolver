import json
import unittest

from tests.temp_helpers import workspace_temp_dir

from gui.settings import EvolverSettings


class TestEvolverSettings(unittest.TestCase):

    def test_defaults(self):
        s = EvolverSettings()
        self.assertEqual(s.interval_minutes, 10)
        self.assertFalse(s.start_with_windows)

    def test_save_and_load_round_trip(self):
        with workspace_temp_dir() as tmp:
            path = tmp / "settings.json"
            s = EvolverSettings(interval_minutes=5, start_with_windows=True)
            s.save(path)

            loaded = EvolverSettings.load(path)
            self.assertEqual(loaded.interval_minutes, 5)
            self.assertTrue(loaded.start_with_windows)

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


if __name__ == "__main__":
    unittest.main()
