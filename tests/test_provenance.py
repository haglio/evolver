"""Where Evolver keeps what made a file, and the stamps it keeps there."""
from __future__ import annotations

import unittest

from app_support import provenance as stamps

from util import provenance


class TestAStampWrittenAfterTheFact(unittest.TestCase):
    def test_has_exactly_the_keys_a_stamp_taken_at_the_time_has(self):
        taken_at_the_time = stamps.stamp("example", anchor=__file__)

        self.assertEqual(set(provenance.reconstructed("example")), set(taken_at_the_time))


if __name__ == "__main__":
    unittest.main()
