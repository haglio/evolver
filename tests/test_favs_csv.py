import unittest
from pathlib import Path

from util import favs_csv

BASE = Path("C:/base")


class TestLocalPath(unittest.TestCase):
    def test_reads_the_path_a_cell_points_at(self):
        cases = [
            ("C:\\Users\\file.mp4", Path("C:/Users/file.mp4")),
            ("D:/videos/clip.mp4", Path("D:/videos/clip.mp4")),
            ("file:///C:/videos/clip.mp4", Path("C:/videos/clip.mp4")),
            ("\\\\server\\share\\file.mp4", Path("\\\\server\\share\\file.mp4")),
            ("subdir/file.mp4", BASE / "subdir/file.mp4"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(favs_csv.local_path(value, BASE), expected)

    def test_reads_through_a_hyperlink_wrapper(self):
        self.assertEqual(
            favs_csv.local_path('=HYPERLINK("file:///C:/videos/clip.mp4";"label")', BASE),
            Path("C:/videos/clip.mp4"),
        )

    def test_reports_no_path_for_a_cell_that_is_not_one(self):
        for value in ("https://example.com/page", "http://example.com/", "just-a-name", ""):
            with self.subTest(value=value):
                self.assertIsNone(favs_csv.local_path(value, BASE))


class TestWithLocalPath(unittest.TestCase):
    def test_rewrites_both_halves_of_a_hyperlink(self):
        moved_to = Path("C:/videos/non_AI/other/clip.mp4")

        rewritten = favs_csv.with_local_path(
            '=HYPERLINK("file:///C:/videos/other/clip.mp4";"C:\\videos\\other\\clip.mp4")',
            moved_to,
        )

        self.assertEqual(
            rewritten,
            '=HYPERLINK("file:///C:/videos/non_AI/other/clip.mp4";"C:\\videos\\non_AI\\other\\clip.mp4")',
        )

    def test_a_bare_path_cell_stays_bare(self):
        self.assertEqual(
            favs_csv.with_local_path("clips/old.mp4", Path("C:/videos/new.mp4")),
            str(Path("C:/videos/new.mp4")),
        )


if __name__ == "__main__":
    unittest.main()
