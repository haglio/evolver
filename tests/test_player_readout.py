from __future__ import annotations

import unittest

from PyQt6.QtCore import QLoggingCategory

from util.player_readout import FORMAT_DUMP, silence_the_ffmpeg_format_dump


class TestTheFormatDump(unittest.TestCase):
    def tearDown(self):
        QLoggingCategory.setFilterRules("")

    def test_a_player_opening_a_video_prints_nothing_of_it(self):
        silence_the_ffmpeg_format_dump()

        self.assertFalse(QLoggingCategory(FORMAT_DUMP).isInfoEnabled())


if __name__ == "__main__":
    unittest.main()
