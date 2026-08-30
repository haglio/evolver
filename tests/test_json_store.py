"""The small JSON files the app keeps, and the one way they are written."""

import json
import unittest
from unittest.mock import patch

from tests.temp_helpers import workspace_temp_dir
from util import json_store


class TestReadDict(unittest.TestCase):
    def test_reads_back_what_was_written(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text(json.dumps({"a": 1}), encoding="utf-8")

            self.assertEqual(json_store.read_dict(path), {"a": 1})

    def test_a_missing_file_is_empty(self):
        with workspace_temp_dir() as root:
            self.assertEqual(json_store.read_dict(root / "none.json"), {})

    def test_a_half_written_file_is_empty(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text('{"a":', encoding="utf-8")

            self.assertEqual(json_store.read_dict(path), {})

    def test_valid_json_that_is_not_a_mapping_is_empty(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text("[1, 2]", encoding="utf-8")

            self.assertEqual(json_store.read_dict(path), {})


class TestReadDictStrict(unittest.TestCase):
    """For a file another app owns: stop, rather than treat it as empty and
    write a new one over the top."""

    def test_reads_back_what_was_written(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text(json.dumps({"a": 1}), encoding="utf-8")

            self.assertEqual(json_store.read_dict_strict(path), {"a": 1})

    def test_a_missing_file_raises(self):
        with workspace_temp_dir() as root:
            with self.assertRaises(OSError):
                json_store.read_dict_strict(root / "none.json")

    def test_a_half_written_file_raises(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text('{"a":', encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                json_store.read_dict_strict(path)


class TestAtomicWriteText(unittest.TestCase):
    def test_the_text_lands_and_nothing_is_left_beside_it(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"

            json_store.atomic_write_text(path, "hello")

            self.assertEqual(path.read_text(encoding="utf-8"), "hello")
            self.assertEqual([p.name for p in root.iterdir()], ["a.json"])

    def test_it_makes_the_directory_it_writes_into(self):
        with workspace_temp_dir() as root:
            path = root / "not" / "yet" / "a.json"

            json_store.atomic_write_text(path, "hello")

            self.assertTrue(path.is_file())

    def test_a_write_that_dies_part_way_leaves_the_old_file_whole(self):
        """The reason this exists: the sidecar tree is written by three apps,
        and a reader must see either the old file or the new one."""
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text("the old one", encoding="utf-8")

            with patch("pathlib.Path.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    json_store.atomic_write_text(path, "the new one")

            self.assertEqual(path.read_text(encoding="utf-8"), "the old one")

    def test_the_line_ending_rule_is_the_callers(self):
        """Each format keeps the endings it has always had: the sidecars take
        the platform's, the files another app parses keep theirs as written."""
        with workspace_temp_dir() as root:
            kept = root / "kept.txt"
            json_store.atomic_write_text(kept, "one\ntwo\n", newline="\n")

            self.assertEqual(kept.read_bytes(), b"one\ntwo\n")


if __name__ == "__main__":
    unittest.main()
