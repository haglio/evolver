from __future__ import annotations

import json
import unittest

from app_support import funscript

from tests.temp_helpers import (
    make_video,
    override_config,
    workspace_temp_dir,
    write_sidecar,
)
from tests.temp_helpers import (
    nonai_library_overrides as library_overrides,
)
from util import nonai_retire, script_library, sidecar


class TestRetireIntoTheBucket(unittest.TestCase):
    def test_an_unset_archive_keeps_the_user_s_own_retire_folder(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4")
            make_video(non_ai / "lagoon" / "2 do not need work" / "placeholder.mp4")

            with override_config(**overrides):
                nonai_retire.retire_original(source, archive_root=None)

            assert (non_ai / "lagoon" / "2 do not need work" / "Lee-Poe.mp4").exists()
            assert not source.exists()

    def test_carries_the_sidecar_to_the_retire_folder(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4")
            make_video(non_ai / "lagoon" / "2 do not need work" / "placeholder.mp4")

            with override_config(**overrides):
                write_sidecar(
                    sidecar.sidecar_path(source),
                    {"clip": {"compilation": "Vol6", "index": 1}},
                )

                nonai_retire.retire_original(source, archive_root=None)

                dest = non_ai / "lagoon" / "2 do not need work" / "Lee-Poe.mp4"
                assert dest.exists()
                assert not source.exists()
                assert not sidecar.sidecar_path(source).exists()
                assert sidecar.read(sidecar.sidecar_path(dest))["clip"] == {"compilation": "Vol6", "index": 1}

    def test_carries_the_funscript_to_the_retire_folder(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4")
            make_video(non_ai / "lagoon" / "2 do not need work" / "placeholder.mp4")

            with override_config(**overrides):
                script = script_library.script_path_for_video(source)
                funscript.write(script, {"actions": [{"at": 0, "pos": 20}]})

                nonai_retire.retire_original(source, archive_root=None)

                dest = non_ai / "lagoon" / "2 do not need work" / "Lee-Poe.mp4"
                assert not script.exists()
                assert funscript.read(script_library.script_path_for_video(dest)) == {"actions": [{"at": 0, "pos": 20}]}

    def test_the_mark_saying_no_person_wrote_the_funscript_goes_with_it(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "example" / "1 clips to upscale" / "scene one.mp4")
            make_video(non_ai / "example" / "2 do not need work" / "placeholder.mp4")

            with override_config(**overrides):
                script = script_library.script_path_for_video(source)
                funscript.write(script, {"actions": []})
                script_library.mark_generated(script)

                nonai_retire.retire_original(source, archive_root=None)

                dest = non_ai / "example" / "2 do not need work" / "scene one.mp4"
                assert script_library.is_marked_generated(script_library.script_path_for_video(dest))
                assert not script_library.is_marked_generated(script)


class TestRetireToAnArchive(unittest.TestCase):
    def test_the_original_lands_in_the_archive_at_its_library_path(self):
        with workspace_temp_dir() as root:
            archive = root / "archive"
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4")
            make_video(non_ai / "lagoon" / "2 do not need work" / "placeholder.mp4")

            with override_config(**overrides):
                nonai_retire.retire_original(source, archive_root=archive)

            assert not source.exists()
            assert (archive / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4").exists()

    def test_the_funscript_goes_with_it_rather_than_being_stranded(self):
        with workspace_temp_dir() as root:
            archive = root / "archive"
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4")

            with override_config(**overrides):
                script = script_library.script_path_for_video(source)
                funscript.write(script, {"actions": [{"at": 0, "pos": 20}]})

                nonai_retire.retire_original(source, archive_root=archive)

                assert not script.exists()
            archived = archive / "lagoon" / "1 clips to upscale" / "Lee-Poe.funscript"
            assert json.loads(archived.read_text(encoding="utf-8")) == {"actions": [{"at": 0, "pos": 20}]}

    def test_no_mark_is_left_behind_for_a_funscript_that_left_the_library(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            source = make_video(overrides["NON_AI_DIR"] / "example" / "1 clips to upscale"
                                / "scene one.mp4")

            with override_config(**overrides):
                script = script_library.script_path_for_video(source)
                funscript.write(script, {"actions": []})
                script_library.mark_generated(script)

                nonai_retire.retire_original(source, archive_root=root / "archive")

                assert not script_library.is_marked_generated(script)

    def test_the_sidecar_goes_with_it_so_the_archive_describes_itself(self):
        with workspace_temp_dir() as root:
            archive = root / "archive"
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4")

            with override_config(**overrides):
                write_sidecar(
                    sidecar.sidecar_path(source),
                    {"clip": {"compilation": "Volume One", "index": 1}},
                )

                nonai_retire.retire_original(source, archive_root=archive)

                assert not sidecar.sidecar_path(source).exists()
            archived = archive / "lagoon" / "1 clips to upscale" / "Lee-Poe.json"
            assert json.loads(archived.read_text(encoding="utf-8"))["clip"] == {"compilation": "Volume One", "index": 1}


class TestCarryMetadata(unittest.TestCase):
    def test_the_footage_keys_cross_and_the_file_scoped_one_does_not(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4")
            out = make_video(
                non_ai / "lagoon" / "3_good_to_go" / "processed"
                / "Lee-Poe_apo8_iris2.mp4"
            )

            with override_config(**overrides):
                write_sidecar(sidecar.sidecar_path(source), {
                    "version": {"group": "Lee-Poe", "processed": False},
                    "video": {"action": "alpha"},
                    "clip": {"compilation": "Volume One", "index": 1},
                })

                assert nonai_retire.carry_metadata(source, out)
                carried = sidecar.read(sidecar.sidecar_path(out))

            assert carried["video"] == {"action": "alpha"}
            assert carried["clip"] == {"compilation": "Volume One", "index": 1}
            assert "version" not in carried

    def test_carrying_the_same_record_twice_writes_nothing_the_second_time(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4")
            out = make_video(
                non_ai / "lagoon" / "3_good_to_go" / "processed"
                / "Lee-Poe_apo8_iris2.mp4"
            )

            with override_config(**overrides):
                write_sidecar(sidecar.sidecar_path(source),
                              {"clip": {"compilation": "Volume One", "index": 1}})

                assert nonai_retire.carry_metadata(source, out)
                assert not nonai_retire.carry_metadata(source, out)

    def test_an_original_with_nothing_to_say_carries_nothing(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "lagoon" / "1 clips to upscale" / "Lee-Poe.mp4")
            out = make_video(non_ai / "lagoon" / "3_good_to_go" / "Lee-Poe_iris2.mp4")

            with override_config(**overrides):
                assert not nonai_retire.carry_metadata(source, out)
                assert not sidecar.sidecar_path(out).exists()


if __name__ == "__main__":
    unittest.main()
