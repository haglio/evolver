"""A video's soundtrack saved on its own, faked at ffmpeg."""
from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from tests.temp_helpers import workspace_temp_dir
from util.sound import save_as_mp3


def _ffmpeg_writing_its_output(calls: list):
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        with open(argv[-1], "wb") as out:
            out.write(b"mp3")
        return subprocess.CompletedProcess(argv, 0, b"", b"")
    return run


class TestSaveAsMp3(unittest.TestCase):
    def test_the_sound_lands_under_the_name_asked_for_and_nothing_else_is_left(self):
        calls = []
        with workspace_temp_dir() as root, \
             patch("util.sound.subprocess.run", side_effect=_ffmpeg_writing_its_output(calls)):
            mp3 = root / "audio" / "loop one.mp3"
            save_as_mp3(root / "loop one.mp4", mp3)

            self.assertEqual(sorted(p.name for p in mp3.parent.iterdir()), ["loop one.mp3"])
        argv, kwargs = calls[0]
        self.assertEqual(argv[argv.index("-i") + 1], str(root / "loop one.mp4"))
        self.assertIn(".partial.", argv[-1])
        self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)

    def test_the_sound_takes_no_tags_from_the_video(self):
        """ComfyUI writes the prompt into a video's tags; a copy of them in the
        sound file would carry it somewhere else."""
        calls = []
        with workspace_temp_dir() as root, \
             patch("util.sound.subprocess.run", side_effect=_ffmpeg_writing_its_output(calls)):
            save_as_mp3(root / "loop.mp4", root / "loop.mp3")
        argv, _kwargs = calls[0]
        self.assertEqual(argv[argv.index("-map_metadata") + 1], "-1")
        self.assertIn("-vn", argv)


if __name__ == "__main__":
    unittest.main()
