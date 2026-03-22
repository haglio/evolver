import json
import unittest

import config
from tasks import bookmarks_sync
from tests.temp_helpers import workspace_temp_dir


class TestBookmarksSync(unittest.TestCase):
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
                json.dumps(
                    {
                        "profile": {
                            "info_cache": {
                                "Profile 2": {
                                    "name": "Blair",
                                }
                            }
                        }
                    }
                ),
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

            saved = {
                "FUN_TIME_FAVS_FILE": config.FUN_TIME_FAVS_FILE,
                "CHROME_USER_DATA_DIR": config.CHROME_USER_DATA_DIR,
                "CHROME_PROFILE_NAME": config.CHROME_PROFILE_NAME,
                "CHROME_BOOKMARKS_FOLDER_NAME": config.CHROME_BOOKMARKS_FOLDER_NAME,
            }
            config.FUN_TIME_FAVS_FILE = favs_path
            config.CHROME_USER_DATA_DIR = user_data_dir
            config.CHROME_PROFILE_NAME = "Blair"
            config.CHROME_BOOKMARKS_FOLDER_NAME = "Fun Time Favs"
            try:
                result = bookmarks_sync.run()
            finally:
                for key, value in saved.items():
                    setattr(config, key, value)

            self.assertTrue(result.ok)
            self.assertEqual(result.added, 2)
            self.assertEqual(result.skipped_blank, 1)
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

            saved = {
                "FUN_TIME_FAVS_FILE": config.FUN_TIME_FAVS_FILE,
                "CHROME_USER_DATA_DIR": config.CHROME_USER_DATA_DIR,
                "CHROME_PROFILE_NAME": config.CHROME_PROFILE_NAME,
            }
            config.FUN_TIME_FAVS_FILE = favs_path
            config.CHROME_USER_DATA_DIR = user_data_dir
            config.CHROME_PROFILE_NAME = "Blair"
            try:
                result = bookmarks_sync.run()
            finally:
                for key, value in saved.items():
                    setattr(config, key, value)

            self.assertFalse(result.ok)
            self.assertTrue(result.profile_missing)


if __name__ == "__main__":
    unittest.main()
