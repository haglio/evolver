"""The two ways this app reads one of its small JSON files."""
from __future__ import annotations

import json
import unittest

from tests.temp_helpers import workspace_temp_dir
from util import json_reads


class TestReadDict(unittest.TestCase):
    def test_reads_back_what_was_written(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text(json.dumps({"a": 1}), encoding="utf-8")

            self.assertEqual(json_reads.read_dict(path), {"a": 1})

    def test_a_missing_file_is_empty(self):
        with workspace_temp_dir() as root:
            self.assertEqual(json_reads.read_dict(root / "none.json"), {})

    def test_a_half_written_file_is_empty(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text('{"a":', encoding="utf-8")

            self.assertEqual(json_reads.read_dict(path), {})

    def test_valid_json_that_is_not_a_mapping_is_empty(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text("[1, 2]", encoding="utf-8")

            self.assertEqual(json_reads.read_dict(path), {})


class TestReadDictStrict(unittest.TestCase):
    """For a file another app owns: stop, rather than treat it as empty and
    write a new one over the top."""

    def test_reads_back_what_was_written(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text(json.dumps({"a": 1}), encoding="utf-8")

            self.assertEqual(json_reads.read_dict_strict(path), {"a": 1})

    def test_a_missing_file_raises(self):
        with workspace_temp_dir() as root, self.assertRaises(OSError):
            json_reads.read_dict_strict(root / "none.json")

    def test_a_half_written_file_raises(self):
        with workspace_temp_dir() as root:
            path = root / "a.json"
            path.write_text('{"a":', encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                json_reads.read_dict_strict(path)


if __name__ == "__main__":
    unittest.main()
