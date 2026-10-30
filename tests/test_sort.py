from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import sort as sort_task
from tasks import upscale
from tests.temp_helpers import (
    LaneLibrary,
    gallery_of_videos_made_again,
    override_config,
    touch_video,
    workspace_temp_dir,
    write_sidecar,
)
from util import lanes, provenance, sidecar, topaz
from util.sidecar import upscaled_video_path


class TestSortHelpers(unittest.TestCase):
    def test_move_unique_moves_when_no_collision(self):
        with workspace_temp_dir() as td_path:
            src = td_path / "src.mp4"
            dest = td_path / "dest.mp4"
            src.write_text("x", encoding="utf-8")

            moved = sort_task._move_unique(src, dest)

            self.assertTrue(moved)
            self.assertFalse(src.exists())
            self.assertTrue(dest.exists())

    def test_move_unique_deletes_src_on_collision(self):
        with workspace_temp_dir() as td_path:
            src = td_path / "src.mp4"
            dest = td_path / "dest.mp4"
            src.write_text("src", encoding="utf-8")
            dest.write_text("dest", encoding="utf-8")

            moved = sort_task._move_unique(src, dest)

            self.assertFalse(moved)
            self.assertFalse(src.exists())
            self.assertEqual(dest.read_text(encoding="utf-8"), "dest")

    def test_run_processes_dynamic_source_directory(self):
        with workspace_temp_dir() as td_path:
            inbox = td_path / "0_inbox"
            sorted_dir = td_path / "1_sorted"
            dynamic_source = "newsource"
            source_dir = inbox / dynamic_source
            source_dir.mkdir(parents=True)
            src = source_dir / "clip.mp4"
            src.write_bytes(b"video")

            with override_config(INBOX_DIR=inbox, SORTED_DIR=sorted_dir):
                with patch("tasks.sort.orientation_of", return_value="landscape"):
                    result = sort_task.run()

            self.assertEqual(result.moved, 1)
            self.assertTrue((sorted_dir / dynamic_source / "landscape" / "clip.mp4").exists())
            self.assertFalse(src.exists())

    def test_run_clears_the_source_folder_it_emptied(self):
        """The inbox is swept after every run, not after a switch."""
        with workspace_temp_dir() as td_path:
            inbox = td_path / "0_inbox"
            sorted_dir = td_path / "1_sorted"
            source_dir = inbox / "newsource" / "landscape"
            source_dir.mkdir(parents=True)
            (source_dir / "clip.mp4").write_bytes(b"video")

            with override_config(INBOX_DIR=inbox, SORTED_DIR=sorted_dir):
                with patch("tasks.sort.orientation_of", return_value="landscape"):
                    sort_task.run()

            self.assertFalse(source_dir.exists())

    def test_run_sorts_between_the_folders_it_is_given(self):
        """The two folders the stage moves between are arguments to it.

        `config` still answers when the caller names nothing — everything else
        in this file relies on that, and so does the pipeline — but the
        signature now says what the stage touches instead of leaving a reader
        to grep the body for it. The ambient inbox and sorted root here are
        paths that do not exist: a stage still reaching for them would create
        the sorted one on its first line.
        """
        with workspace_temp_dir() as td_path:
            inbox = td_path / "given_inbox"
            sorted_dir = td_path / "given_sorted"
            (inbox / "examplesource").mkdir(parents=True)
            (inbox / "examplesource" / "clip one.mp4").write_bytes(b"video")
            ambient = td_path / "ambient"

            with override_config(INBOX_DIR=ambient / "0_inbox", SORTED_DIR=ambient / "1_sorted"):
                with patch("tasks.sort.orientation_of", return_value="portrait"):
                    result = sort_task.run(inbox_dir=inbox, sorted_dir=sorted_dir)

            self.assertEqual(result.moved, 1)
            self.assertTrue((sorted_dir / "examplesource" / "portrait" / "clip one.mp4").exists())
            self.assertFalse(ambient.exists())


class TestAVideoOrigeneratorMadeAgain(unittest.TestCase):
    def _sent_before(self, lib: LaneLibrary, name: str) -> tuple[Path, Path]:
        source = lanes.ORIGENERATOR_SOURCE
        sorted_copy = lib.sorted_dir / source / "portrait" / name
        sorted_copy.parent.mkdir(parents=True)
        sorted_copy.write_bytes(b"first made")
        upscaled = touch_video(upscaled_video_path(source, "portrait", sorted_copy.stem))
        current = topaz.AI_UPSCALE_ORIGENERATOR
        write_sidecar(sidecar.sidecar_path(upscaled), provenance.recorded(
            {"favorite": True}, provenance.UPSCALE,
            provenance.reconstructed("evolver", method=current.name,
                                     method_version=current.version)))
        return sorted_copy, upscaled

    def _sent_again(self, lib: LaneLibrary, name: str, content: bytes) -> Path:
        handed_over = lib.inbox / lanes.ORIGENERATOR_SOURCE / name
        handed_over.parent.mkdir(parents=True)
        handed_over.write_bytes(content)
        with patch("tasks.sort.orientation_of", return_value="portrait"):
            sort_task.run()
        return handed_over

    def test_takes_the_place_of_its_sorted_copy_and_has_its_upscale_made_again(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            gallery = gallery_of_videos_made_again(root / "gallery.db", ["made_00001.mp4"])
            with lib.config(ORIGENERATOR_DB_PATH=gallery):
                sorted_copy, upscaled = self._sent_before(lib, "made_00001.mp4")

                handed_over = self._sent_again(lib, "made_00001.mp4", b"made again")

                self.assertFalse(handed_over.exists())
                self.assertEqual(sorted_copy.read_bytes(), b"made again")
                self.assertEqual(upscale.collect_candidates(),
                                 [(sorted_copy, lanes.ORIGENERATOR_SOURCE, "portrait")])
                self.assertTrue(sidecar.read(sidecar.sidecar_path(upscaled))["favorite"])

    def test_sent_again_as_it_already_is_leaves_its_upscale_alone(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            gallery = gallery_of_videos_made_again(root / "gallery.db", ["made_00001.mp4"])
            with lib.config(ORIGENERATOR_DB_PATH=gallery):
                sorted_copy, _upscaled = self._sent_before(lib, "made_00001.mp4")

                handed_over = self._sent_again(lib, "made_00001.mp4", b"first made")

                self.assertFalse(handed_over.exists())
                self.assertEqual(sorted_copy.read_bytes(), b"first made")
                self.assertEqual(upscale.collect_candidates(), [])


if __name__ == "__main__":
    unittest.main()
