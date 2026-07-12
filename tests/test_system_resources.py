import unittest

from util import system_resources


class TestAvailableRam(unittest.TestCase):
    def test_reports_a_plausible_available_amount(self):
        available = system_resources.available_ram_gb()
        self.assertGreater(available, 0.0)
        self.assertLess(available, 4096.0)


if __name__ == "__main__":
    unittest.main()
