import json
import unittest

from tasks import bookmarks_sync
from tests.temp_helpers import override_config, workspace_temp_dir


def chrome_profile(root, profile="Profile 2", name="Jane Doe"):
    """A User Data tree with one named profile; the shape every sync test built
    by hand. Returns (user_data_dir, bookmarks_path)."""
    user_data_dir = root / "User Data"
    profile_dir = user_data_dir / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    (user_data_dir / "Local State").write_text(
        json.dumps({"profile": {"info_cache": {profile: {"name": name}}}}),
        encoding="utf-8",
    )
    return user_data_dir, profile_dir / "Bookmarks"


def _folder(guid, node_id, name, children):
    return {
        "children": children,
        "date_added": "1",
        "date_last_used": "0",
        "date_modified": "1",
        "guid": guid,
        "id": node_id,
        "name": name,
        "type": "folder",
    }


def chrome_bookmarks_payload(favs_children=()):
    """A minimal Chrome Bookmarks file: the bar holding one Fun Time Favs
    folder with *favs_children*, plus the empty other/synced roots."""
    return {
        "checksum": "",
        "roots": {
            "bookmark_bar": _folder(
                "bar-guid", "1", "Bookmarks bar",
                [_folder("folder-guid", "10", "Fun Time Favs", list(favs_children))],
            ),
            "other": _folder("other-guid", "2", "Other bookmarks", []),
            "synced": _folder("synced-guid", "3", "Mobile bookmarks", []),
        },
        "version": 1,
    }


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
            user_data_dir, bookmarks_path = chrome_profile(root)
            favs_path.write_text(
                "file,web_url\n"
                f"{existing_media.relative_to(root)},https://example.com/keep\n"
                f"{missing_media.relative_to(root)},https://example.com/drop\n",
                encoding="utf-8",
            )

            with override_config(
                FUN_TIME_FAVS_FILE=favs_path,
                CHROME_USER_DATA_DIR=user_data_dir,
                CHROME_PROFILE_NAME="Jane Doe",
                CHROME_BOOKMARKS_FOLDER_NAME="Fun Time Favs",
            ):
                result = bookmarks_sync.run()

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
            user_data_dir, bookmarks_path = chrome_profile(root)
            favs_path.write_text(
                "local_file,web_url\n"
                f'"=HYPERLINK(""file:///{existing_media.as_posix()}"";""{existing_media!s}"")",https://example.com/keep\n'
                f'"=HYPERLINK(""file:///{missing_media.as_posix()}"";""{missing_media!s}"")",https://example.com/drop\n',
                encoding="utf-8",
            )

            with override_config(
                FUN_TIME_FAVS_FILE=favs_path,
                CHROME_USER_DATA_DIR=user_data_dir,
                CHROME_PROFILE_NAME="Jane Doe",
                CHROME_BOOKMARKS_FOLDER_NAME="Fun Time Favs",
            ):
                result = bookmarks_sync.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.pruned, 1)
            self.assertEqual(result.synced, 1)
            self.assertIn("https://example.com/keep", favs_path.read_text(encoding="utf-8"))
            self.assertNotIn("https://example.com/drop", favs_path.read_text(encoding="utf-8"))
            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            folder = written["roots"]["bookmark_bar"]["children"][0]
            self.assertEqual([child["url"] for child in folder["children"]], ["https://example.com/keep"])

    def test_run_syncs_web_urls_into_named_profile_folder(self):
        with workspace_temp_dir() as root:
            favs_path = root / "favs.csv"
            user_data_dir, bookmarks_path = chrome_profile(root)
            favs_path.write_text(
                "local_file,web_url\n"
                'one,"=HYPERLINK(""https://example.net/image/abc"";""https://example.net/image/abc"")"\n'
                "two,https://example.com/image/xyz\n"
                "three,\n",
                encoding="utf-8",
            )
            bookmarks_path.write_text(
                json.dumps(chrome_bookmarks_payload([
                    {"id": "20", "name": "old", "type": "url", "url": "https://old.example/"},
                ])),
                encoding="utf-8",
            )

            with override_config(
                FUN_TIME_FAVS_FILE=favs_path,
                CHROME_USER_DATA_DIR=user_data_dir,
                CHROME_PROFILE_NAME="Jane Doe",
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
            user_data_dir, bookmarks_path = chrome_profile(root)
            favs_path.write_text(
                "local_file,web_url\n"
                "one,https://example.com/same\n"
                "two,https://example.com/same\n"
                "three,https://example.com/different\n",
                encoding="utf-8",
            )

            with override_config(
                FUN_TIME_FAVS_FILE=favs_path,
                CHROME_USER_DATA_DIR=user_data_dir,
                CHROME_PROFILE_NAME="Jane Doe",
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
                CHROME_PROFILE_NAME="Jane Doe",
            ):
                result = bookmarks_sync.run()

            self.assertFalse(result.ok)
            self.assertTrue(result.profile_missing)

    def test_run_uses_the_favorites_file_and_profile_it_is_given(self):
        """Four things reach outside this repo, and all four are arguments now.

        `config` still answers when the caller names none of them, which is
        every other test here and the pipeline itself. Pointing the ambient
        four at a profile that would sync a different URL is what proves the
        given ones are the ones used, rather than merely accepted.
        """
        with workspace_temp_dir() as root:
            given_favs = root / "given" / "favs.csv"
            given_favs.parent.mkdir(parents=True)
            given_favs.write_text("web_url\nhttps://example.com/given\n", encoding="utf-8")
            given_user_data, given_bookmarks = chrome_profile(root / "given", name="Robin")

            ambient_favs = root / "ambient" / "favs.csv"
            ambient_favs.parent.mkdir(parents=True)
            ambient_favs.write_text("web_url\nhttps://example.com/ambient\n", encoding="utf-8")
            ambient_user_data, _ = chrome_profile(root / "ambient", name="Ambient")

            with override_config(
                FUN_TIME_FAVS_FILE=ambient_favs,
                CHROME_USER_DATA_DIR=ambient_user_data,
                CHROME_PROFILE_NAME="Ambient",
                CHROME_BOOKMARKS_FOLDER_NAME="Ambient Folder",
            ):
                result = bookmarks_sync.run(
                    favs_file=given_favs,
                    chrome_user_data_dir=given_user_data,
                    chrome_profile_name="Robin",
                    bookmarks_folder_name="Given Folder",
                )

            self.assertTrue(result.ok)
            self.assertEqual(result.synced, 1)
            written = json.loads(given_bookmarks.read_text(encoding="utf-8"))
            folder = written["roots"]["bookmark_bar"]["children"][0]
            self.assertEqual(folder["name"], "Given Folder")
            self.assertEqual([child["url"] for child in folder["children"]], ["https://example.com/given"])


if __name__ == "__main__":
    unittest.main()
