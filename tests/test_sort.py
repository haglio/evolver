import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import sort as sort_task
from tests.temp_helpers import workspace_temp_dir


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

    def test_remove_empty_dirs_removes_only_empty(self):
        with workspace_temp_dir() as root:
            empty_sub = root / "a" / "b"
            nonempty_sub = root / "c"
            empty_sub.mkdir(parents=True)
            nonempty_sub.mkdir(parents=True)
            (nonempty_sub / "file.txt").write_text("x", encoding="utf-8")

            sort_task._remove_empty_dirs(root)

            self.assertFalse((root / "a").exists())
            self.assertTrue(nonempty_sub.exists())

    def test_run_processes_dynamic_source_directory(self):
        with workspace_temp_dir() as td_path:
            inbox = td_path / "0_inbox"
            sorted_dir = td_path / "1_sorted"
            dynamic_source = "newsource"
            source_dir = inbox / dynamic_source
            source_dir.mkdir(parents=True)
            src = source_dir / "clip.mp4"
            src.write_bytes(b"video")

            old_inbox = sort_task.config.INBOX_DIR
            old_sorted = sort_task.config.SORTED_DIR
            old_clean = sort_task.config.CLEAN_EMPTY_INBOX_DIRS

            sort_task.config.INBOX_DIR = inbox
            sort_task.config.SORTED_DIR = sorted_dir
            sort_task.config.CLEAN_EMPTY_INBOX_DIRS = False
            try:
                with patch("tasks.sort.get_orientation", return_value="landscape"):
                    result = sort_task.run()

                self.assertEqual(result.moved, 1)
                self.assertTrue((sorted_dir / dynamic_source / "landscape" / "clip.mp4").exists())
                self.assertFalse(src.exists())
            finally:
                sort_task.config.INBOX_DIR = old_inbox
                sort_task.config.SORTED_DIR = old_sorted
                sort_task.config.CLEAN_EMPTY_INBOX_DIRS = old_clean


if __name__ == "__main__":
    unittest.main()
