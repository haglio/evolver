import unittest
from unittest.mock import patch

from tasks import purge_weird
from tests.temp_helpers import LaneLibrary, override_config, touch_video, workspace_temp_dir


class TestPurgeWeird(unittest.TestCase):
    def test_source_stem_strips_known_processing_suffixes(self):
        cases = [
            ("clip_topaz", "clip"),
            ("clip_topaz_cfr", "clip"),
            ("clip_apo8_gcg5_topaz", "clip_apo8_gcg5"),
            ("clip_apo8_gcg5", "clip"),
            ("clip_apo8_gcg5_Copy(2)", "clip"),
            ("clip_topaz_extra", "clip"),
            ("clip", "clip"),
            ("no_suffix_at_all", "no_suffix_at_all"),
            ("a_b_topaz", "a_b"),
            ("clip_apo8_gcg5_topaz_cfr", "clip_apo8_gcg5"),
        ]
        for stem, expected in cases:
            with self.subTest(stem=stem):
                self.assertEqual(purge_weird.source_stem(stem), expected)

    def test_run_deletes_weird_and_matching_preprocessed_sorted_file(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            weird_dir.mkdir(parents=True)
            sorted_file = sorted_dir / "sourceA" / "landscape" / "clip_apo8_gcg5.mp4"
            sorted_file.parent.mkdir(parents=True)
            sorted_file.write_bytes(b"sorted")
            weird_file = weird_dir / "clip_apo8_gcg5_topaz.mp4"
            weird_file.write_bytes(b"weird")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir):
                result = purge_weird.run()

            self.assertEqual(result.deleted_weird, 1)
            self.assertEqual(result.deleted_sorted, 1)
            self.assertEqual(result.missing_sorted, [])
            self.assertFalse(weird_file.exists())
            self.assertFalse(sorted_file.exists())

    def test_run_deletes_weird_and_matching_sorted_file(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            weird_dir.mkdir(parents=True)
            sorted_file = sorted_dir / "sourceA" / "landscape" / "clip.mp4"
            sorted_file.parent.mkdir(parents=True)
            sorted_file.write_bytes(b"sorted")
            weird_file = weird_dir / "clip_topaz.mp4"
            weird_file.write_bytes(b"weird")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir):
                result = purge_weird.run()

            self.assertEqual(result.deleted_weird, 1)
            self.assertEqual(result.deleted_sorted, 1)
            self.assertEqual(result.missing_sorted, [])
            self.assertFalse(weird_file.exists())
            self.assertFalse(sorted_file.exists())

    def test_a_name_with_glob_characters_still_finds_its_source(self):
        # The lookup handed the file name to rglob as a pattern, so a name with
        # `[`, `*` or `?` in it matched nothing: the stage said no source was
        # found, popped its dialog, and deleted the weird file anyway, orphaning
        # the source forever (bug 17).
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            metadata_dir = root / "metadata"
            weird_dir.mkdir(parents=True)
            sorted_file = sorted_dir / "sourceA" / "landscape" / "clip [1].mp4"
            sorted_file.parent.mkdir(parents=True)
            sorted_file.write_bytes(b"sorted")
            json_file = metadata_dir / "2_outbox" / "clip [1]_topaz.json"
            json_file.parent.mkdir(parents=True)
            json_file.write_text("{}", encoding="utf-8")
            weird_file = weird_dir / "clip [1]_topaz.mp4"
            weird_file.write_bytes(b"weird")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir, METADATA_DIR=metadata_dir):
                result = purge_weird.run()

            self.assertEqual(result.missing_sorted, [])
            self.assertEqual(result.deleted_sorted, 1)
            self.assertEqual(result.deleted_metadata, 1)
            self.assertFalse(sorted_file.exists())
            self.assertFalse(json_file.exists())
            self.assertFalse(weird_file.exists())

    def test_run_deletes_orphaned_metadata_json(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            metadata_dir = root / "metadata"
            weird_dir.mkdir(parents=True)
            weird_file = weird_dir / "clip_topaz.mp4"
            weird_file.write_bytes(b"weird")
            # Metadata JSON lives under a different subpath than kinda_weird,
            # mirroring where the file was scraped before it was moved to weird.
            json_file = metadata_dir / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider" / "clip_topaz.json"
            json_file.parent.mkdir(parents=True)
            json_file.write_text('{"video":{"prompt":"test"}}', encoding="utf-8")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir, METADATA_DIR=metadata_dir):
                with patch("tasks.purge_weird.show_error"):
                    result = purge_weird.run()

            self.assertEqual(result.deleted_weird, 1)
            self.assertEqual(result.deleted_metadata, 1)
            self.assertFalse(json_file.exists())

    def test_run_shows_popup_when_matching_sorted_file_missing(self):
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            weird_dir.mkdir(parents=True)
            weird_file = weird_dir / "missing_topaz.mp4"
            weird_file.write_bytes(b"weird")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.purge_weird.show_error") as show_error:
                    result = purge_weird.run()

            self.assertEqual(result.deleted_weird, 1)
            self.assertEqual(result.deleted_sorted, 0)
            self.assertEqual(result.missing_sorted, ["missing_topaz.mp4"])
            show_error.assert_called_once()
            self.assertFalse(weird_file.exists())

    def test_run_deletes_every_sorted_copy_matching_the_source_name(self):
        """Pinned as it behaves today: one weird file whose source basename
        lives under two source folders loses BOTH copies -- rglob matches by
        name alone, and every match is unlinked (audit probe P13 narrowed the
        loop to one match with the suite unchanged). Whether deleting both is
        the intended behaviour is recorded in the changelog as a question,
        not answered here."""
        with workspace_temp_dir() as root:
            weird_dir = root / "weird"
            sorted_dir = root / "sorted"
            weird_dir.mkdir(parents=True)
            copy_a = sorted_dir / "sourceA" / "landscape" / "clip.mp4"
            copy_b = sorted_dir / "sourceB" / "portrait" / "clip.mp4"
            for copy in (copy_a, copy_b):
                copy.parent.mkdir(parents=True)
                copy.write_bytes(b"sorted")
            (weird_dir / "clip_topaz.mp4").write_bytes(b"weird")

            with override_config(SORTED_DIR=sorted_dir, WEIRD_DIR=weird_dir):
                result = purge_weird.run()

            self.assertEqual(result.deleted_sorted, 2)
            self.assertEqual(result.missing_sorted, [])
            self.assertFalse(copy_a.exists())
            self.assertFalse(copy_b.exists())


class TestPurgeGenausPile(unittest.TestCase):
    """Genau condemns a clip into a pile of its own, beside the folder it plays
    from. The sweep reaches that pile too -- for years it reached only the
    outbox's, and every clip Genau condemned sat there forever (bug 11)."""

    def test_a_clip_genau_condemned_goes_with_its_sidecar_and_its_sorted_source(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                condemned = touch_video(lib.genau_weird / "loop_7_topaz.mp4")
                source = touch_video(
                    lib.sorted_dir / "example-loop-clips" / "landscape" / "loop_7.mp4"
                )
                sidecar = lib.metadata / "genau" / "clips" / "loop_7_topaz.json"
                sidecar.parent.mkdir(parents=True, exist_ok=True)
                sidecar.write_text("{}", encoding="utf-8")

                result = purge_weird.run()

                self.assertEqual(result.deleted_weird, 1)
                self.assertEqual(result.deleted_sorted, 1)
                self.assertEqual(result.deleted_metadata, 1)
                self.assertEqual(result.missing_sorted, [])
                self.assertFalse(condemned.exists())
                self.assertFalse(source.exists())
                self.assertFalse(sidecar.exists())

    def test_only_the_genau_lanes_own_corner_of_sorted_is_searched(self):
        """A condemned loop takes the lane's sorted copy and nothing else.

        The outbox pile's files come from any source folder, so its lookup
        searches the whole of ``1_sorted`` by name; a Genau clip's source can
        only ever be under the lane's own source folder, and a video that
        merely shares its stem elsewhere is another lane's."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                touch_video(lib.genau_weird / "loop_7_topaz.mp4")
                lane_source = touch_video(
                    lib.sorted_dir / "example-loop-clips" / "landscape" / "loop_7.mp4"
                )
                namesake = touch_video(
                    lib.sorted_dir / "other-source" / "portrait" / "loop_7.mp4"
                )

                result = purge_weird.run()

                self.assertEqual(result.deleted_sorted, 1)
                self.assertFalse(lane_source.exists())
                self.assertTrue(namesake.exists())

    def test_a_condemned_loop_with_no_sorted_source_left_raises_no_alert(self):
        """The lane retires a loop's ``1_sorted`` copy the moment it delivers
        it (``tasks.genau_deliver``), so a condemned loop with no source is the
        ordinary case in this pile -- not the orphan the outbox pile reports.
        Counting it would pop a Windows dialog for every clip Genau condemns."""
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                condemned = touch_video(lib.genau_weird / "loop_9_topaz.mp4")

                with patch("tasks.purge_weird.show_error") as show_error:
                    result = purge_weird.run()

                self.assertEqual(result.deleted_weird, 1)
                self.assertEqual(result.missing_sorted, [])
                show_error.assert_not_called()
                self.assertFalse(condemned.exists())


if __name__ == "__main__":
    unittest.main()
