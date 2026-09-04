import unittest
from pathlib import Path

from tests.temp_helpers import workspace_temp_dir
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


class TestLocalCell(unittest.TestCase):
    def test_is_written_the_way_fun_time_writes_it(self):
        """Fun Time finds its own row by this exact text, so a row written any
        other way is one it cannot see, cannot skip and cannot remove."""
        self.assertEqual(
            favs_csv.local_cell(Path("C:/videos/some folder/clip one.mp4")),
            '=HYPERLINK("file:///C:/videos/some%20folder/clip%20one.mp4";"C:\\videos\\some folder\\clip one.mp4")',
        )

    def test_with_local_path_encodes_a_space_the_same_way(self):
        rewritten = favs_csv.with_local_path(
            '=HYPERLINK("file:///C:/videos/old.mp4";"C:\\videos\\old.mp4")',
            Path("C:/videos/new one.mp4"),
        )

        self.assertEqual(rewritten, favs_csv.local_cell(Path("C:/videos/new one.mp4")))


class TestFavoriteRows(unittest.TestCase):
    def test_a_favorite_is_appended_and_the_file_is_created_with_its_header_when_absent(self):
        with workspace_temp_dir() as root:
            favs = root / "favs.csv"

            self.assertTrue(favs_csv.add_favorite(favs, Path("C:/videos/clip a.mp4")))

            self.assertEqual(
                favs.read_bytes().decode("utf-8"),
                "local_file,web_url\r\n"
                '"=HYPERLINK(""file:///C:/videos/clip%20a.mp4"";""C:\\videos\\clip a.mp4"")",\r\n',
            )
            self.assertEqual(favs_csv.favorite_videos(favs), [Path("C:/videos/clip a.mp4")])

    def test_a_video_already_listed_is_left_alone_whatever_its_case(self):
        with workspace_temp_dir() as root:
            favs = root / "favs.csv"
            favs_csv.add_favorite(favs, Path("C:/videos/Clip.mp4"))

            self.assertFalse(favs_csv.add_favorite(favs, Path("c:/videos/clip.mp4")))

            self.assertEqual(len(favs_csv.favorite_videos(favs)), 1)

    def test_removing_a_favorite_drops_its_row_and_keeps_the_rest(self):
        with workspace_temp_dir() as root:
            favs = root / "favs.csv"
            favs.write_text(
                "local_file,web_url\r\n"
                '"=HYPERLINK(""file:///C:/videos/keep.mp4"";""C:\\videos\\keep.mp4"")",https://example.test/keep\r\n'
                '"=HYPERLINK(""file:///C:/videos/gone.mp4"";""C:\\videos\\gone.mp4"")",\r\n',
                encoding="utf-8",
            )

            self.assertTrue(favs_csv.remove_favorite(favs, Path("c:/videos/GONE.mp4")))
            self.assertFalse(favs_csv.remove_favorite(favs, Path("C:/videos/never.mp4")))

            self.assertEqual(favs_csv.favorite_videos(favs), [Path("C:/videos/keep.mp4")])
            self.assertIn("https://example.test/keep", favs.read_text(encoding="utf-8"))

    def test_no_file_means_no_favorites_and_nothing_to_remove(self):
        with workspace_temp_dir() as root:
            self.assertEqual(favs_csv.favorite_videos(root / "favs.csv"), [])
            self.assertFalse(favs_csv.remove_favorite(root / "favs.csv", Path("C:/videos/x.mp4")))


if __name__ == "__main__":
    unittest.main()
