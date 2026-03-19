import tempfile
import unittest
from pathlib import Path

from tasks import sort as sort_task


class TestSortHelpers(unittest.TestCase):
    def test_move_unique_moves_when_no_collision(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            src = td_path / "src.mp4"
            dest = td_path / "dest.mp4"
            src.write_text("x", encoding="utf-8")

            moved = sort_task._move_unique(src, dest)

            self.assertTrue(moved)
            self.assertFalse(src.exists())
            self.assertTrue(dest.exists())

    def test_move_unique_deletes_src_on_collision(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            src = td_path / "src.mp4"
            dest = td_path / "dest.mp4"
            src.write_text("src", encoding="utf-8")
            dest.write_text("dest", encoding="utf-8")

            moved = sort_task._move_unique(src, dest)

            self.assertFalse(moved)
            self.assertFalse(src.exists())
            self.assertEqual(dest.read_text(encoding="utf-8"), "dest")

    def test_remove_empty_dirs_removes_only_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            empty_sub = root / "a" / "b"
            nonempty_sub = root / "c"
            empty_sub.mkdir(parents=True)
            nonempty_sub.mkdir(parents=True)
            (nonempty_sub / "file.txt").write_text("x", encoding="utf-8")

            sort_task._remove_empty_dirs(root)

            self.assertFalse((root / "a").exists())
            self.assertTrue(nonempty_sub.exists())


if __name__ == "__main__":
    unittest.main()
