from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import sort as sort_task
from tasks import upscale
from tests.gallery_fakes import FakeGallery, a_gallery_of
from tests.temp_helpers import (
    LaneLibrary,
    override_config,
    touch_video,
    workspace_temp_dir,
    write_sidecar,
)
from util import lanes, provenance, script_library, sidecar, topaz


class TestSortHelpers(unittest.TestCase):
    def test_move_unique_moves_when_no_collision(self):
        with workspace_temp_dir() as td_path:
            src = td_path / "src.mp4"
            dest = td_path / "dest.mp4"
            src.write_text("x", encoding="utf-8")

            moved = sort_task._move_unique(src, dest)

            assert moved
            assert not src.exists()
            assert dest.exists()

    def test_move_unique_deletes_src_on_collision(self):
        with workspace_temp_dir() as td_path:
            src = td_path / "src.mp4"
            dest = td_path / "dest.mp4"
            src.write_text("src", encoding="utf-8")
            dest.write_text("dest", encoding="utf-8")

            moved = sort_task._move_unique(src, dest)

            assert not moved
            assert not src.exists()
            assert dest.read_text(encoding="utf-8") == "dest"

    def test_run_processes_dynamic_source_directory(self):
        with workspace_temp_dir() as td_path:
            inbox = td_path / "0_inbox"
            sorted_dir = td_path / "1_sorted"
            dynamic_source = "newsource"
            source_dir = inbox / dynamic_source
            source_dir.mkdir(parents=True)
            src = source_dir / "clip.mp4"
            src.write_bytes(b"video")

            with (
                override_config(INBOX_DIR=inbox, SORTED_DIR=sorted_dir),
                patch("tasks.sort.orientation_of", return_value="landscape"),
            ):
                result = sort_task.run()

            assert result.moved == 1
            assert (sorted_dir / dynamic_source / "landscape" / "clip.mp4").exists()
            assert not src.exists()

    def test_run_clears_the_source_folder_it_emptied(self):
        with workspace_temp_dir() as td_path:
            inbox = td_path / "0_inbox"
            sorted_dir = td_path / "1_sorted"
            source_dir = inbox / "newsource" / "landscape"
            source_dir.mkdir(parents=True)
            (source_dir / "clip.mp4").write_bytes(b"video")

            with (
                override_config(INBOX_DIR=inbox, SORTED_DIR=sorted_dir),
                patch("tasks.sort.orientation_of", return_value="landscape"),
            ):
                sort_task.run()

            assert not source_dir.exists()

    def test_run_sorts_between_the_folders_it_is_given(self):
        with workspace_temp_dir() as td_path:
            inbox = td_path / "given_inbox"
            sorted_dir = td_path / "given_sorted"
            (inbox / "examplesource").mkdir(parents=True)
            (inbox / "examplesource" / "clip one.mp4").write_bytes(b"video")
            ambient = td_path / "ambient"

            with (
                override_config(INBOX_DIR=ambient / "0_inbox", SORTED_DIR=ambient / "1_sorted"),
                patch("tasks.sort.orientation_of", return_value="portrait"),
            ):
                result = sort_task.run(inbox_dir=inbox, sorted_dir=sorted_dir)

            assert result.moved == 1
            assert (sorted_dir / "examplesource" / "portrait" / "clip one.mp4").exists()
            assert not ambient.exists()


def write_sidecar_for(video: Path) -> Path:
    write_sidecar(sidecar.sidecar_path(video), {})
    return sidecar.sidecar_path(video)


class TestAVideoOrigeneratorMadeAgain(unittest.TestCase):
    def setUp(self):
        self.gallery = FakeGallery()

    def _sent_before(self, lib: LaneLibrary, name: str, *, made_again: tuple[str, ...]) -> tuple[Path, Path]:
        source = lanes.ORIGENERATOR_SOURCE
        sorted_copy = lib.sorted_dir / source / "portrait" / name
        sorted_copy.parent.mkdir(parents=True)
        sorted_copy.write_bytes(b"first made")
        upscaled = touch_video(lanes.upscale_of(source, "portrait", sorted_copy.stem))
        current = topaz.AI_UPSCALE_ORIGENERATOR
        made_by = provenance.reconstructed("evolver", method=current.name,
                                           method_version=current.version)
        a_gallery_of(lib.search_root.parent / "gallery.db", [
            {"prompt_id": f"made-{number}", "remade_at": "2026-01-02 03:04:05",
             "output_files": json.dumps([{"filename": made, "subfolder": "video"}]),
             "evolver_upscale": str(upscaled), "upscale_provenance": json.dumps(made_by)}
            for number, made in enumerate(made_again)])
        return sorted_copy, upscaled

    def _sent_again(self, lib: LaneLibrary, name: str, content: bytes) -> Path:
        handed_over = lib.inbox / lanes.ORIGENERATOR_SOURCE / name
        handed_over.parent.mkdir(parents=True)
        handed_over.write_bytes(content)
        with patch("tasks.sort.orientation_of", return_value="portrait"):
            sort_task.run(gallery=self.gallery)
        return handed_over

    def test_takes_the_place_of_its_sorted_copy_and_the_gallery_forgets_what_made_its_upscale(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "gallery.db"):
                sorted_copy, upscaled = self._sent_before(
                    lib, "made_00001.mp4", made_again=("made_00001.mp4",))

                handed_over = self._sent_again(lib, "made_00001.mp4", b"made again")

                assert not handed_over.exists()
                assert sorted_copy.read_bytes() == b"made again"
                assert self.gallery.upscales == [(upscaled, provenance.reconstructed(None))]

    def test_made_again_under_its_new_name_takes_the_place_of_the_copy_under_the_old(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "gallery.db"):
                old_copy, old_upscale = self._sent_before(
                    lib, "made_00001_.mp4", made_again=("made_00001-audio.mp4", "made_00001.mp4"))
                old_script = script_library.script_path_for_video(old_upscale)
                old_script.parent.mkdir(parents=True)
                old_script.write_text("{}", encoding="utf-8")
                where_its_record_was = write_sidecar_for(old_upscale)

                self._sent_again(lib, "made_00001-audio.mp4", b"made again")

                remake = old_copy.with_name("made_00001-audio.mp4")
                its_upscale = lanes.upscale_of(lanes.ORIGENERATOR_SOURCE, "portrait", remake.stem)
                assert not old_copy.exists()
                assert not old_upscale.exists()
                assert remake.read_bytes() == b"made again"
                assert self.gallery.upscales == [(its_upscale, provenance.reconstructed(None))]
                assert script_library.script_path_for_video(its_upscale).is_file()
                assert not old_script.exists()
                assert where_its_record_was.exists()
                assert not sidecar.sidecar_path(its_upscale).exists()

    def test_sent_again_as_it_already_is_leaves_its_upscale_alone(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "gallery.db"):
                sorted_copy, _upscaled = self._sent_before(
                    lib, "made_00001.mp4", made_again=("made_00001.mp4",))

                handed_over = self._sent_again(lib, "made_00001.mp4", b"first made")

                assert not handed_over.exists()
                assert sorted_copy.read_bytes() == b"first made"
                assert self.gallery.upscales == []
                assert upscale.collect_queued_videos(upscale.UpscaleFolders.configured()) == []

    def test_a_gallery_that_cannot_forget_what_made_the_upscale_is_said_in_the_log(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            self.gallery = FakeGallery(None)
            with lib.config(ORIGENERATOR_DB_PATH=root / "gallery.db"), \
                    self.assertLogs("tasks.sort", level="WARNING") as said:
                self._sent_before(lib, "made_00001.mp4", made_again=("made_00001.mp4",))
                self._sent_again(lib, "made_00001.mp4", b"made again")

        assert any("did not forget what made" in line for line in said.output)


if __name__ == "__main__":
    unittest.main()
