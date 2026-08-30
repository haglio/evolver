"""Where a superseded original goes, and what the upscale keeps of it.

These moved out of tests/test_nonai_upscale.py with the moves themselves. They
no longer say where an original goes by overriding config: the archive root is
an argument, so each case names the answer it is about — a path, or None for
the bucket's own ``2*`` folder.
"""

import json
import unittest

from tests.temp_helpers import (
    make_video,
    nonai_library_overrides as library_overrides,
    override_config,
    workspace_temp_dir,
)
from util import funscript, nonai_retire, sidecar


class TestRetireIntoTheBucket(unittest.TestCase):
    """With no archive configured — the public checkout's case — the original
    goes to the bucket's ``2*`` folder, as the user does by hand."""

    def test_an_unset_archive_keeps_the_user_s_own_retire_folder(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4")
            make_video(non_ai / "larkin" / "2 do not need work" / "placeholder.mp4")

            with override_config(**overrides):
                nonai_retire.retire_original(source, archive_root=None)

            self.assertTrue(
                (non_ai / "larkin" / "2 do not need work" / "Lee-Poe.mp4").exists()
            )
            self.assertFalse(source.exists())

    def test_carries_the_sidecar_to_the_retire_folder(self):
        """A clip's `clip` metadata must follow the file when it is retired, or
        it is orphaned and pruned — losing Nau's navigation data."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4")
            make_video(non_ai / "larkin" / "2 do not need work" / "placeholder.mp4")

            with override_config(**overrides):
                sidecar.write(
                    sidecar.sidecar_path(source),
                    {"clip": {"compilation": "Vol6", "index": 1}},
                )

                nonai_retire.retire_original(source, archive_root=None)

                dest = non_ai / "larkin" / "2 do not need work" / "Lee-Poe.mp4"
                self.assertTrue(dest.exists())
                self.assertFalse(source.exists())
                self.assertFalse(sidecar.sidecar_path(source).exists())
                self.assertEqual(
                    sidecar.read(sidecar.sidecar_path(dest))["clip"],
                    {"compilation": "Vol6", "index": 1},
                )

    def test_carries_the_funscript_to_the_retire_folder(self):
        """A script left in the old folder still matches the moved video, so the
        scripts sync would relocate it — but the clip-scripts stage runs first
        and writes the clip a fresh script at the new path, and the sync then
        fails the whole run on a collision nothing can resolve."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4")
            make_video(non_ai / "larkin" / "2 do not need work" / "placeholder.mp4")

            with override_config(**overrides):
                script = funscript.script_path_for_video(source)
                funscript.write(script, {"actions": [{"at": 0, "pos": 20}]})

                nonai_retire.retire_original(source, archive_root=None)

                dest = non_ai / "larkin" / "2 do not need work" / "Lee-Poe.mp4"
                self.assertFalse(script.exists())
                self.assertEqual(
                    funscript.read(funscript.script_path_for_video(dest)),
                    {"actions": [{"at": 0, "pos": 20}]},
                )


class TestRetireToAnArchive(unittest.TestCase):
    """With an archive given, a retired original leaves the library entirely.

    The bucket's ``2*`` folder sits on the working drive inside the file-sync
    pair, so every finished encode left roughly a gigabyte of superseded source
    behind and the drive filled up. An archive root points those files at
    somewhere else — cloud storage, another volume — and the library keeps only
    what is watched.
    """

    def test_the_original_lands_in_the_archive_at_its_library_path(self):
        with workspace_temp_dir() as root:
            archive = root / "archive"
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4")
            make_video(non_ai / "larkin" / "2 do not need work" / "placeholder.mp4")

            with override_config(**overrides):
                nonai_retire.retire_original(source, archive_root=archive)

            self.assertFalse(source.exists())
            self.assertTrue(
                (archive / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4").exists()
            )

    def test_the_funscript_goes_with_it_rather_than_being_left_behind(self):
        """A script left in the library still matches the archived video by name,
        so the scripts sync tries to relocate it — and the clip-scripts stage has
        already written a fresh script at that destination, so the sync fails the
        run on a collision nothing can resolve."""
        with workspace_temp_dir() as root:
            archive = root / "archive"
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4")

            with override_config(**overrides):
                script = funscript.script_path_for_video(source)
                funscript.write(script, {"actions": [{"at": 0, "pos": 20}]})

                nonai_retire.retire_original(source, archive_root=archive)

                self.assertFalse(script.exists())
            archived = archive / "larkin" / "1 clips to upscale" / "Lee-Poe.funscript"
            self.assertEqual(
                json.loads(archived.read_text(encoding="utf-8")),
                {"actions": [{"at": 0, "pos": 20}]},
            )

    def test_the_sidecar_goes_with_it_so_the_archive_describes_itself(self):
        """The metadata tree mirrors the library, and the grouping stage prunes
        any sidecar no library video maps to — so a sidecar left behind is
        deleted on the next run, taking the clip's provenance with it."""
        with workspace_temp_dir() as root:
            archive = root / "archive"
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4")

            with override_config(**overrides):
                sidecar.write(
                    sidecar.sidecar_path(source),
                    {"clip": {"compilation": "Volume One", "index": 1}},
                )

                nonai_retire.retire_original(source, archive_root=archive)

                self.assertFalse(sidecar.sidecar_path(source).exists())
            archived = archive / "larkin" / "1 clips to upscale" / "Lee-Poe.json"
            self.assertEqual(
                json.loads(archived.read_text(encoding="utf-8"))["clip"],
                {"compilation": "Volume One", "index": 1},
            )


class TestCarryMetadata(unittest.TestCase):
    def test_the_footage_keys_cross_and_the_file_scoped_one_does_not(self):
        """``version`` describes the file, not the footage — the original is not
        a processed variant and the upscale is, and the grouping stage is the one
        thing that gets to say so."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4")
            out = make_video(
                non_ai / "larkin" / "3_good_to_go" / "processed"
                / "Lee-Poe_apo8_iris2.mp4"
            )

            with override_config(**overrides):
                sidecar.write(sidecar.sidecar_path(source), {
                    "version": {"group": "Lee-Poe", "processed": False},
                    "video": {"action": "alpha"},
                    "clip": {"compilation": "Volume One", "index": 1},
                })

                self.assertTrue(nonai_retire.carry_metadata(source, out))
                carried = sidecar.read(sidecar.sidecar_path(out))

            self.assertEqual(carried["video"], {"action": "alpha"})
            self.assertEqual(carried["clip"], {"compilation": "Volume One", "index": 1})
            self.assertNotIn("version", carried)

    def test_carrying_the_same_record_twice_writes_nothing_the_second_time(self):
        """The repair pass runs on every tick forever, so a no-op has to say so
        rather than rewriting every sidecar in the library each time."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4")
            out = make_video(
                non_ai / "larkin" / "3_good_to_go" / "processed"
                / "Lee-Poe_apo8_iris2.mp4"
            )

            with override_config(**overrides):
                sidecar.write(sidecar.sidecar_path(source),
                              {"clip": {"compilation": "Volume One", "index": 1}})

                self.assertTrue(nonai_retire.carry_metadata(source, out))
                self.assertFalse(nonai_retire.carry_metadata(source, out))

    def test_an_original_with_nothing_to_say_carries_nothing(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4")
            out = make_video(non_ai / "larkin" / "3_good_to_go" / "Lee-Poe_iris2.mp4")

            with override_config(**overrides):
                self.assertFalse(nonai_retire.carry_metadata(source, out))
                self.assertFalse(sidecar.sidecar_path(out).exists())

    def test_an_archived_originals_sidecar_is_read_from_beside_it(self):
        """Outside the library the mirrored metadata tree cannot answer, so the
        archived copy describes itself from the file next to it."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            archived = root / "archive" / "larkin" / "Lee-Poe.mp4"
            make_video(archived)
            archived.with_suffix(".json").write_text(
                json.dumps({"clip": {"compilation": "Volume One", "index": 1}}),
                encoding="utf-8",
            )
            out = make_video(
                overrides["NON_AI_DIR"] / "larkin" / "3_good_to_go" / "processed"
                / "Lee-Poe_apo8_iris2.mp4"
            )

            with override_config(**overrides):
                self.assertTrue(nonai_retire.carry_metadata(archived, out))
                carried = sidecar.read(sidecar.sidecar_path(out))

            self.assertEqual(carried["clip"], {"compilation": "Volume One", "index": 1})


class TestArchivedOriginal(unittest.TestCase):
    def test_finds_the_one_original_of_that_name_anywhere_under_the_archive(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            wanted = make_video(root / "archive" / "1 clips to upscale" / "Lee-Poe.mp4")
            make_video(root / "archive" / "0 unsorted" / "someone else.mp4")

            with override_config(**overrides):
                found = nonai_retire.archived_original(root / "archive", "Lee-Poe")

            self.assertEqual(found, wanted)

    def test_two_of_a_name_is_no_answer_rather_than_a_guess(self):
        """Nothing here can say which of them the upscale came from, and a guess
        writes one clip's provenance onto another's footage."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(root / "archive" / "0 unsorted" / "Lee-Poe.mp4")
            make_video(root / "archive" / "1 clips to upscale" / "Lee-Poe.mp4")

            with override_config(**overrides):
                self.assertIsNone(
                    nonai_retire.archived_original(root / "archive", "Lee-Poe"))

    def test_a_title_holding_glob_characters_still_matches_itself(self):
        """Read as a pattern, "[Example Studio] scene one" is a character class
        that matches none of its own name, so the match is by stem."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            stem = "[Example Studio] scene one"
            wanted = make_video(root / "archive" / "0 unsorted" / f"{stem}.mp4")

            with override_config(**overrides):
                found = nonai_retire.archived_original(root / "archive", stem)

            self.assertEqual(found, wanted)


if __name__ == "__main__":
    unittest.main()
