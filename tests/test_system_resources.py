import unittest

from util import system_resources


class TestAvailableRam(unittest.TestCase):
    def test_reports_a_plausible_available_amount(self):
        available = system_resources.available_ram_gb()
        self.assertGreater(available, 0.0)
        self.assertLess(available, 4096.0)


class TestSecondsSinceLastInput(unittest.TestCase):
    def test_returns_a_nonnegative_plausible_number(self):
        idle = system_resources.seconds_since_last_input()
        self.assertIsInstance(idle, float)
        self.assertGreaterEqual(idle, 0.0)
        # A real session is never idle for weeks; a wildly large value would
        # mean the GetTickCount wrap arithmetic went wrong.
        self.assertLess(idle, 60 * 60 * 24 * 30)


if __name__ == "__main__":
    unittest.main()
