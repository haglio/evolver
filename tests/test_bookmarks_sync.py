import json
import unittest

from tasks import bookmarks_sync
from tests.temp_helpers import override_config, workspace_temp_dir


class TestExtractUrl(unittest.TestCase):
    def test_extracts_plain_urls(self):
        cases = [
            ("https://example.com/page", "https://example.com/page"),
            ("http://example.com/", "http://example.com/"),
            ("not-a-url", None),
            ("ftp://example.com/", None),
            ("", None),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(bookmarks_sync._extract_url(value), expected)

    def test_extracts_hyperlink_formulas(self):
        self.assertEqual(
            bookmarks_sync._extract_url('=HYPERLINK("https://example.com/abc";"label")'),
            "https://example.com/abc",
        )
        self.assertIsNone(bookmarks_sync._extract_url('=HYPERLINK("not-a-url";"label")'))


class TestBookmarkName(unittest.TestCase):
    def test_generates_name_from_url(self):
        cases = [
            ("https://example.com/image/abc", "example.com - abc"),
            ("https://example.net/image/xyz", "example.net - xyz"),
            ("https://example.com/", "https://example.com/"),
            ("https://example.com", "https://example.com"),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(bookmarks_sync._bookmark_name(url), expected)


class TestBookmarksSync(unittest.TestCase):
    def test_run_prunes_rows_with_missing_source_files_before_sync(self):
        with workspace_temp_dir() as root:
            existing_media = root / "clips" / "keep.mp4"
            existing_media.parent.mkdir(parents=True, exist_ok=True)
            existing_media.write_text("x", encoding="utf-8")
            missing_media = root / "clips" / "missing.mp4"
            favs_path = root / "favs.csv"
            user_data_dir = root / "User Data"
            profile_dir = user_data_dir / "Profile 2"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            favs_path.write_text(
                "file,web_url\n"
                f"{existing_media.relative_to(root)},https://example.com/keep\n"
                f"{missing_media.relative_to(root)},https://example.com/drop\n",
                encoding="utf-8",
            )
            (user_data_dir / "Local State").write_text(
                json.dumps({"profile": {"info_cache": {"Profile 2": {"name": "Blair"}}}}),
                encoding="utf-8",
            )

            with override_config(
                FUN_TIME_FAVS_FILE=favs_path,
                CHROME_USER_DATA_DIR=user_data_dir,
                CHROME_PROFILE_NAME="Blair",
                CHROME_BOOKMARKS_FOLDER_NAME="Fun Time Favs",
            ):
                result = bookmarks_sync.run()

            bookmarks_path = profile_dir / "Bookmarks"
            self.assertTrue(result.ok)
            self.assertEqual(result.pruned, 1)
            self.assertEqual(result.synced, 1)
            self.assertEqual(
                favs_path.read_text(encoding="utf-8").splitlines(),
                [
                    "file,web_url",
                    "clips\\keep.mp4,https://example.com/keep",
                ],
            )
            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            folder = written["roots"]["bookmark_bar"]["children"][0]
            self.assertEqual([child["url"] for child in folder["children"]], ["https://example.com/keep"])

    def test_run_prunes_hyperlink_local_file_rows_with_missing_sources(self):
        with workspace_temp_dir() as root:
            existing_media = root / "clips" / "keep clip.mp4"
            existing_media.parent.mkdir(parents=True, exist_ok=True)
            existing_media.write_text("x", encoding="utf-8")
            missing_media = root / "clips" / "missing clip.mp4"
            favs_path = root / "favs.csv"
            user_data_dir = root / "User Data"
            profile_dir = user_data_dir / "Profile 2"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            favs_path.write_text(
                "local_file,web_url\n"
                '"=HYPERLINK(""file:///{}"";""{}"")",https://example.com/keep\n'
                '"=HYPERLINK(""file:///{}"";""{}"")",https://example.com/drop\n'.format(
                    existing_media.as_posix(),
                    str(existing_media),
                    missing_media.as_posix(),
                    str(missing_media),
                ),
                encoding="utf-8",
            )
            (user_data_dir / "Local State").write_text(
                json.dumps({"profile": {"info_cache": {"Profile 2": {"name": "Blair"}}}}),
                encoding="utf-8",
            )

            with override_config(
                FUN_TIME_FAVS_FILE=favs_path,
                CHROME_USER_DATA_DIR=user_data_dir,
                CHROME_PROFILE_NAME="Blair",
                CHROME_BOOKMARKS_FOLDER_NAME="Fun Time Favs",
            ):
                result = bookmarks_sync.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.pruned, 1)
            self.assertEqual(result.synced, 1)
            self.assertIn("https://example.com/keep", favs_path.read_text(encoding="utf-8"))
            self.assertNotIn("https://example.com/drop", favs_path.read_text(encoding="utf-8"))
            bookmarks_path = profile_dir / "Bookmarks"
            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            folder = written["roots"]["bookmark_bar"]["children"][0]
            self.assertEqual([child["url"] for child in folder["children"]], ["https://example.com/keep"])

    def test_run_syncs_web_urls_into_named_profile_folder(self):
        with workspace_temp_dir() as root:
            favs_path = root / "favs.csv"
            user_data_dir = root / "User Data"
            profile_dir = user_data_dir / "Profile 2"
            bookmarks_path = profile_dir / "Bookmarks"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            favs_path.write_text(
                "local_file,web_url\n"
                'one,"=HYPERLINK(""https://example.net/image/abc"";""https://example.net/image/abc"")"\n'
                "two,https://example.com/image/xyz\n"
                "three,\n",
                encoding="utf-8",
            )
            (user_data_dir / "Local State").write_text(
                json.dumps({"profile": {"info_cache": {"Profile 2": {"name": "Blair"}}}}),
                encoding="utf-8",
            )
            bookmarks_path.write_text(
                json.dumps(
                    {
                        "checksum": "",
                        "roots": {
                            "bookmark_bar": {
                                "children": [
                                    {
                                        "children": [
                                            {
                                                "id": "20",
                                                "name": "old",
                                                "type": "url",
                                                "url": "https://old.example/",
                                            }
                                        ],
                                        "date_added": "1",
                                        "date_last_used": "0",
                                        "date_modified": "1",
                                        "guid": "folder-guid",
                                        "id": "10",
                                        "name": "Fun Time Favs",
                                        "type": "folder",
                                    }
                                ],
                                "date_added": "1",
                                "date_last_used": "0",
                                "date_modified": "1",
                                "guid": "bar-guid",
                                "id": "1",
                                "name": "Bookmarks bar",
                                "type": "folder",
                            },
                            "other": {
                                "children": [],
                                "date_added": "1",
                                "date_last_used": "0",
                                "date_modified": "1",
                                "guid": "other-guid",
                                "id": "2",
                                "name": "Other bookmarks",
                                "type": "folder",
                            },
                            "synced": {
                                "children": [],
                                "date_added": "1",
                                "date_last_used": "0",
                                "date_modified": "1",
                                "guid": "synced-guid",
                                "id": "3",
                                "name": "Mobile bookmarks",
                                "type": "folder",
                            },
                        },
                        "version": 1,
                    }
                ),
                encoding="utf-8",
            )

            with override_config(
                FUN_TIME_FAVS_FILE=favs_path,
                CHROME_USER_DATA_DIR=user_data_dir,
                CHROME_PROFILE_NAME="Blair",
                CHROME_BOOKMARKS_FOLDER_NAME="Fun Time Favs",
            ):
                result = bookmarks_sync.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.synced, 2)
            self.assertEqual(result.no_url, 1)
            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            folder = written["roots"]["bookmark_bar"]["children"][0]
            self.assertEqual(folder["name"], "Fun Time Favs")
            self.assertEqual(
                [child["url"] for child in folder["children"]],
                [
                    "https://example.net/image/abc",
                    "https://example.com/image/xyz",
                ],
            )

    def test_run_deduplicates_identical_urls(self):
        with workspace_temp_dir() as root:
            favs_path = root / "favs.csv"
            user_data_dir = root / "User Data"
            profile_dir = user_data_dir / "Profile 2"
            bookmarks_path = profile_dir / "Bookmarks"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            profile_dir.mkdir(parents=True, exist_ok=True)
            favs_path.write_text(
                "local_file,web_url\n"
                "one,https://example.com/same\n"
                "two,https://example.com/same\n"
                "three,https://example.com/different\n",
                encoding="utf-8",
            )
            (user_data_dir / "Local State").write_text(
                json.dumps({"profile": {"info_cache": {"Profile 2": {"name": "Blair"}}}}),
                encoding="utf-8",
            )

            with override_config(
                FUN_TIME_FAVS_FILE=favs_path,
                CHROME_USER_DATA_DIR=user_data_dir,
                CHROME_PROFILE_NAME="Blair",
                CHROME_BOOKMARKS_FOLDER_NAME="Fun Time Favs",
            ):
                result = bookmarks_sync.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.synced, 2)
            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            folder = written["roots"]["bookmark_bar"]["children"][0]
            urls = [child["url"] for child in folder["children"]]
            self.assertEqual(urls, ["https://example.com/same", "https://example.com/different"])

    def test_run_reports_missing_profile(self):
        with workspace_temp_dir() as root:
            favs_path = root / "favs.csv"
            user_data_dir = root / "User Data"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            favs_path.write_text("local_file,web_url\nx,https://example.com/\n", encoding="utf-8")
            (user_data_dir / "Local State").write_text(
                json.dumps({"profile": {"info_cache": {"Default": {"name": "Alex"}}}}),
                encoding="utf-8",
            )

            with override_config(
                FUN_TIME_FAVS_FILE=favs_path,
                CHROME_USER_DATA_DIR=user_data_dir,
                CHROME_PROFILE_NAME="Blair",
            ):
                result = bookmarks_sync.run()

            self.assertFalse(result.ok)
            self.assertTrue(result.profile_missing)


if __name__ == "__main__":
    unittest.main()
