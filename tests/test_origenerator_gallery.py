from __future__ import annotations

import json
import sqlite3
import unittest
from fractions import Fraction

from tests.temp_helpers import workspace_temp_dir
from util import origenerator_gallery


class TestTheRateOrigeneratorsVideosAreGeneratedAt(unittest.TestCase):
    def test_is_read_from_the_document_its_checkout_publishes(self):
        assert _generated_fps_published_in(json.dumps({"generated_fps": 16.0})) == Fraction(16)

    def test_is_unknown_with_no_origenerator_beside_this_one(self):
        with workspace_temp_dir() as root:
            assert origenerator_gallery.generated_fps(root / "origenerator") is None

    def test_is_unknown_to_a_document_written_before_origenerator_published_it(self):
        assert _generated_fps_published_in('{"table": "generations"}') is None

    def test_is_unknown_to_a_document_that_cannot_be_read_as_a_rate(self):
        for document in ("{not json", "[]", '{"generated_fps": "sixteen"}',
                         '{"generated_fps": 0}'):
            with self.subTest(document=document):
                assert _generated_fps_published_in(document) is None


class TestTheGalleryDatabase(unittest.TestCase):
    def test_a_missing_gallery_is_named_in_the_error(self):
        with workspace_temp_dir() as root, self.assertRaises(FileNotFoundError) as raised:
            origenerator_gallery.rows(("output_files",), db_path=root / "gallery.db")

        assert "gallery.db" in str(raised.exception)

    def test_a_column_an_older_gallery_lacks_is_missing_from_every_row(self):
        with workspace_temp_dir() as root:
            db_path = _gallery_with_columns(root, "output_files", [('[{"filename": "a.mp4"}]',)])

            found = origenerator_gallery.rows(("output_files",), optional=("remade_at",), db_path=db_path)

        assert found == [{"output_files": '[{"filename": "a.mp4"}]'}]

    def test_the_gallery_is_opened_so_nothing_here_can_write_to_it(self):
        with workspace_temp_dir() as root:
            db_path = _gallery_with_columns(root, "output_files", [("[]",)])
            connection = origenerator_gallery._connect_ro(db_path)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute("DELETE FROM generations")
            finally:
                connection.close()


class TestWhatAGenerationRowProduced(unittest.TestCase):
    def test_the_file_names_are_the_ones_the_row_lists(self):
        row = {"output_files": json.dumps([{"filename": "a.mp4"}, {"filename": "b.png"}])}

        assert origenerator_gallery.output_names(row) == ["a.mp4", "b.png"]

    def test_a_row_whose_list_cannot_be_read_costs_that_row_and_not_the_run(self):
        assert origenerator_gallery.output_names({"output_files": "{not json"}) == []
        assert origenerator_gallery.output_names({"output_files": '"text"'}) == []

    def test_a_stem_is_taken_back_to_what_arrived_through_every_layer_added_after(self):
        assert origenerator_gallery.origin_stem("scene one (2)_topaz (3)") == "scene one"
        assert origenerator_gallery.origin_stem("scene one_topaz (2)_topaz") == "scene one"

    def test_a_stem_with_nothing_added_comes_back_whole(self):
        assert origenerator_gallery.origin_stem("scene one") == "scene one"


def _gallery_with_columns(root, column: str, values: list[tuple]):
    db_path = root / "gallery.db"
    connection = sqlite3.connect(db_path)
    connection.execute(f"CREATE TABLE generations ({column} TEXT)")
    connection.executemany("INSERT INTO generations VALUES (?)", values)
    connection.commit()
    connection.close()
    return db_path


def _generated_fps_published_in(document: str) -> Fraction | None:
    with workspace_temp_dir() as checkout:
        (checkout / origenerator_gallery.PUBLISHED).write_text(document, encoding="utf-8")
        return origenerator_gallery.generated_fps(checkout)


if __name__ == "__main__":
    unittest.main()
