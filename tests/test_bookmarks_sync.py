from __future__ import annotations

import json
import unittest
from pathlib import Path

from app_support.favorites import mark

from tasks import bookmarks_sync
from tests.gallery_fakes import a_gallery_of, kept_at
from tests.temp_helpers import LaneLibrary, override_config, touch_video, workspace_temp_dir
from util import sidecar


def favorite(library: LaneLibrary, name: str, page: str = "") -> Path:
    video = touch_video(library.non_ai / "alpha" / name)
    with library.config():
        mark(sidecar.sidecar_path(video), True, page=page)
    return video


class SiteFavorites:
    def __init__(self, library: LaneLibrary) -> None:
        self._gallery = library.search_root.parent / "gallery.db"
        self._rows: dict[Path, dict] = {}
        self._metadata = library.metadata
        self._upscales = library.kino_upscales / "portrait" / "a-site"

    def add(self, name: str, page: str = "") -> Path:
        self._metadata.mkdir(parents=True, exist_ok=True)
        video = touch_video(self._upscales / name)
        self._rows[video] = kept_at(f"outside-{len(self._rows)}", video, starred=1, web_url=page,
                                    source="outside")
        self._write()
        return video

    def unstar(self, video: Path) -> None:
        self._rows[video]["starred"] = 0
        self._write()

    def _write(self) -> None:
        self._gallery.unlink(missing_ok=True)
        a_gallery_of(self._gallery, list(self._rows.values()))


def chrome_profile(root, profile="Profile 2", name="Jane Doe"):
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


def chrome_bookmarks_payload(faves_children=(), folder_name="Fun Time Faves"):
    return {
        "checksum": "",
        "roots": {
            "bookmark_bar": _folder(
                "bar-guid", "1", "Bookmarks bar",
                [_folder("folder-guid", "10", folder_name, list(faves_children))],
            ),
            "other": _folder("other-guid", "2", "Other bookmarks", []),
            "synced": _folder("synced-guid", "3", "Mobile bookmarks", []),
        },
        "version": 1,
    }


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
                assert bookmarks_sync._bookmark_name(url) == expected


class TestBookmarksSync(unittest.TestCase):
    def _sync(self, library: LaneLibrary, user_data_dir: Path, **given) -> bookmarks_sync.BookmarksSyncResult:
        with library.config(ORIGENERATOR_DB_PATH=library.search_root.parent / "gallery.db"), \
                override_config(CHROME_USER_DATA_DIR=user_data_dir, CHROME_PROFILE_NAME="Jane Doe"):
            return bookmarks_sync.run(**given)

    def test_run_syncs_the_favorites_pages_into_named_profile_folder(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, bookmarks_path = chrome_profile(root)
            faves.add("scene one.mp4", "https://example.net/image/abc")
            faves.add("scene two.mp4", "https://example.com/image/xyz")
            faves.add("scene three.mp4")
            bookmarks_path.write_text(
                json.dumps(chrome_bookmarks_payload([
                    {"id": "20", "name": "old", "type": "url", "url": "https://old.example/"},
                ])),
                encoding="utf-8",
            )

            result = self._sync(library, user_data_dir)

            assert result.ok
            assert (result.added, result.removed) == (2, 1)
            assert result.untaught == 1
            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            folder = written["roots"]["bookmark_bar"]["children"][0]
            assert folder["name"] == "Fun Time Faves"
            assert sorted(child["url"] for child in folder["children"]) == ["https://example.com/image/xyz", "https://example.net/image/abc"]

    def test_the_folder_under_its_old_spelling_is_renamed_in_place(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, bookmarks_path = chrome_profile(root)
            faves.add("scene one.mp4", "https://example.com/a")
            bookmarks_path.write_text(json.dumps(chrome_bookmarks_payload(
                [{"id": "20", "name": "a", "type": "url", "url": "https://example.com/a"}],
                folder_name="Fun Time Favs",
            )), encoding="utf-8")

            self._sync(library, user_data_dir)

            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            folders = written["roots"]["bookmark_bar"]["children"]
            assert [(folder["name"], folder["guid"]) for folder in folders] == [("Fun Time Faves", "folder-guid")]
            assert [child["url"] for child in folders[0]["children"]] == ["https://example.com/a"]

    def test_a_favorite_from_a_site_evolver_knows_with_no_recorded_page_is_counted_and_not_guessed(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, _bookmarks_path = chrome_profile(root)
            faves.add("1234-abcd_topaz.mp4")

            with override_config(SITE_PAGE_BASES={"a-site": "https://a-site.example"}):
                result = self._sync(library, user_data_dir)

        assert (result.added, result.no_url, result.untaught) == (0, 1, 0)

    def test_a_favorite_from_a_site_evolver_was_never_taught_is_counted_apart(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, _bookmarks_path = chrome_profile(root)
            faves.add("scene one_topaz.mp4")

            with override_config(SITE_PAGE_BASES={}):
                result = self._sync(library, user_data_dir)

        assert (result.added, result.untaught) == (0, 1)

    def test_a_bookmark_already_in_the_folder_is_counted_as_already_there(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, _bookmarks_path = chrome_profile(root)
            faves.add("scene one.mp4", "https://example.com/a")
            self._sync(library, user_data_dir)

            again = self._sync(library, user_data_dir)

        assert (again.added, again.removed, again.already) == (0, 0, 1)

    def test_a_run_that_changes_nothing_adds_and_removes_no_bookmark(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, _bookmarks_path = chrome_profile(root)
            faves.add("scene one.mp4", "https://example.com/a")
            self._sync(library, user_data_dir)

            again = self._sync(library, user_data_dir)

        assert (again.added, again.removed) == (0, 0)

    def test_a_video_no_longer_a_favorite_leaves_the_folder(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, bookmarks_path = chrome_profile(root)
            kept = faves.add("scene one.mp4", "https://example.com/keep")
            dropped = faves.add("scene two.mp4", "https://example.com/drop")
            self._sync(library, user_data_dir)
            faves.unstar(dropped)

            result = self._sync(library, user_data_dir)

            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            urls = [child["url"] for child in written["roots"]["bookmark_bar"]["children"][0]["children"]]
            assert urls == ["https://example.com/keep"]
            assert kept.exists()
        assert (result.added, result.removed) == (0, 1)

    def test_a_favorite_whose_video_is_gone_is_left_out(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, bookmarks_path = chrome_profile(root)
            faves.add("scene one.mp4", "https://example.com/keep")
            faves.add("scene two.mp4", "https://example.com/drop").unlink()

            result = self._sync(library, user_data_dir)

            assert result.added == 1
            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            urls = [child["url"] for child in written["roots"]["bookmark_bar"]["children"][0]["children"]]
            assert urls == ["https://example.com/keep"]

    def test_the_folder_keeps_its_order_and_a_new_favorite_joins_the_end(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, bookmarks_path = chrome_profile(root)
            faves.add("b scene.mp4", "https://example.com/b")
            faves.add("c scene.mp4", "https://example.com/c")
            bookmarks_path.write_text(json.dumps(chrome_bookmarks_payload([
                {"id": "20", "name": "c", "type": "url", "url": "https://example.com/c"},
                {"id": "21", "name": "b", "type": "url", "url": "https://example.com/b"},
            ])), encoding="utf-8")
            faves.add("a scene.mp4", "https://example.com/a")

            self._sync(library, user_data_dir)

            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            urls = [child["url"] for child in written["roots"]["bookmark_bar"]["children"][0]["children"]]
            assert urls == ["https://example.com/c", "https://example.com/b", "https://example.com/a"]

    def test_run_deduplicates_identical_urls(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, _bookmarks_path = chrome_profile(root)
            faves.add("scene one.mp4", "https://example.com/same")
            faves.add("scene two.mp4", "https://example.com/same")
            faves.add("scene three.mp4", "https://example.com/different")

            result = self._sync(library, user_data_dir)

            assert result.ok
            assert result.added == 2

    def test_a_page_that_is_no_web_address_is_counted_and_left_out(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, _bookmarks_path = chrome_profile(root)
            faves.add("scene one.mp4", "file:///C:/not/a/page")

            result = self._sync(library, user_data_dir)

            assert (result.added, result.bad_url) == (0, 1)

    def test_records_that_cannot_be_reached_leave_the_folder_as_it_was(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            user_data_dir, bookmarks_path = chrome_profile(root)
            before = json.dumps(chrome_bookmarks_payload([
                {"id": "20", "name": "a", "type": "url", "url": "https://example.com/a"},
            ]))
            bookmarks_path.write_text(before, encoding="utf-8")

            result = self._sync(library, user_data_dir)

            assert result.added == 0
            assert bookmarks_path.read_text(encoding="utf-8") == before

    def test_an_ai_video_starred_in_the_gallery_is_bookmarked_by_its_page_there(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            user_data_dir, bookmarks_path = chrome_profile(root)
            starred = touch_video(library.kino_upscales / "portrait" / "a-site" / "scene one_topaz.mp4")
            unstarred = touch_video(library.kino_upscales / "portrait" / "a-site" / "scene two_topaz.mp4")
            with library.config():
                mark(sidecar.sidecar_path(unstarred), True, page="https://example.com/old-sidecar")
            a_gallery_of(root / "gallery.db", [
                kept_at("outside-1", starred, starred=1, web_url="https://example.com/starred", source="outside"),
                kept_at("outside-2", unstarred, starred=0, web_url="https://example.com/unstarred", source="outside"),
            ])

            result = self._sync(library, user_data_dir)

            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            urls = [child["url"] for child in written["roots"]["bookmark_bar"]["children"][0]["children"]]
        assert urls == ["https://example.com/starred"]
        assert result.added == 1

    def test_a_starred_video_origenerator_made_has_no_page_to_bookmark_and_is_not_counted(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            user_data_dir, _bookmarks_path = chrome_profile(root)
            upscale = touch_video(library.kino_upscales / "portrait" / "origenerator" / "made_00001__topaz.mp4")
            library.metadata.mkdir(parents=True)
            a_gallery_of(root / "gallery.db", [{
                "prompt_id": "made-1", "starred": 1, "evolver_upscale": str(upscale),
                "output_files": json.dumps([{"filename": "made_00001_.mp4", "subfolder": "video"}])}])

            result = self._sync(library, user_data_dir)

        assert (result.added, result.untaught) == (0, 0)

    def test_a_non_ai_favorite_has_no_page_to_bookmark_and_is_not_counted(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, bookmarks_path = chrome_profile(root)
            faves.add("scene one_topaz.mp4", "https://example.com/site")
            favorite(library, "scene two.mp4", "https://example.com/non-ai")
            favorite(library, "scene three.mp4")

            result = self._sync(library, user_data_dir)

            written = json.loads(bookmarks_path.read_text(encoding="utf-8"))
            urls = [child["url"] for child in written["roots"]["bookmark_bar"]["children"][0]["children"]]
        assert urls == ["https://example.com/site"]
        assert (result.added, result.untaught) == (1, 0)

    def test_a_starred_ai_video_whose_file_is_gone_is_left_out(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            user_data_dir, _bookmarks_path = chrome_profile(root)
            gone = library.kino_upscales / "portrait" / "a-site" / "scene one_topaz.mp4"
            library.metadata.mkdir(parents=True)
            a_gallery_of(root / "gallery.db", [
                kept_at("outside-1", gone, starred=1, web_url="https://example.com/gone", source="outside")])

            result = self._sync(library, user_data_dir)

        assert (result.added, result.untaught) == (0, 0)

    def test_a_gallery_that_cannot_be_read_leaves_the_folder_as_it_was(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir, bookmarks_path = chrome_profile(root)
            faves.add("scene one.mp4", "https://example.com/a")
            before = json.dumps(chrome_bookmarks_payload([
                {"id": "20", "name": "b", "type": "url", "url": "https://example.com/b"},
            ]))
            bookmarks_path.write_text(before, encoding="utf-8")
            (root / "gallery.db").write_bytes(b"not a database, made up for this test")

            result = self._sync(library, user_data_dir)

            assert bookmarks_path.read_text(encoding="utf-8") == before
        assert result.added == 0

    def test_run_reports_missing_profile(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            user_data_dir = root / "User Data"
            user_data_dir.mkdir(parents=True, exist_ok=True)
            faves.add("scene one.mp4", "https://example.com/")
            (user_data_dir / "Local State").write_text(
                json.dumps({"profile": {"info_cache": {"Default": {"name": "Alex"}}}}),
                encoding="utf-8",
            )

            result = self._sync(library, user_data_dir)

            assert not result.ok
            assert result.profile_missing

    def test_run_uses_the_profile_it_is_given(self):
        with workspace_temp_dir() as root:
            library = LaneLibrary(root)
            faves = SiteFavorites(library)
            faves.add("scene one.mp4", "https://example.com/given")
            given_user_data, given_bookmarks = chrome_profile(root / "given", name="Robin")
            ambient_user_data, _ = chrome_profile(root / "ambient", name="Ambient")

            with library.config(), override_config(
                CHROME_USER_DATA_DIR=ambient_user_data,
                CHROME_PROFILE_NAME="Ambient",
                CHROME_BOOKMARKS_FOLDER_NAME="Ambient Folder",
            ):
                result = bookmarks_sync.run(
                    chrome_user_data_dir=given_user_data,
                    chrome_profile_name="Robin",
                    bookmarks_folder_name="Given Folder",
                )

            assert result.ok
            assert result.added == 1
            written = json.loads(given_bookmarks.read_text(encoding="utf-8"))
            folder = written["roots"]["bookmark_bar"]["children"][0]
            assert folder["name"] == "Given Folder"
            assert [child["url"] for child in folder["children"]] == ["https://example.com/given"]


if __name__ == "__main__":
    unittest.main()
