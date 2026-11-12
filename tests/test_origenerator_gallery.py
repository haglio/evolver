from __future__ import annotations

import ast
import json
import sqlite3
import unittest
from fractions import Fraction
from pathlib import Path

import pytest

from tests.product_sources import PROJECT_ROOT, product_sources
from tests.temp_helpers import override_config, workspace_temp_dir
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


def _connects_to_sqlite(node: ast.AST) -> bool:
    if isinstance(node, ast.ImportFrom):
        return node.module == "sqlite3" and any(alias.name == "connect" for alias in node.names)
    return (isinstance(node, ast.Attribute) and node.attr == "connect"
            and isinstance(node.value, ast.Name) and node.value.id == "sqlite3")


class TestTheGalleryDatabase(unittest.TestCase):
    @pytest.mark.repo_check
    def test_nothing_here_connects_to_sqlite_the_gallery_is_read_through_app_support(self):
        opening = [
            f"{name}:{node.lineno}" for name in product_sources(PROJECT_ROOT)
            for node in ast.walk(ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8")))
            if _connects_to_sqlite(node)]

        assert opening == []

    def test_the_rows_come_from_the_gallery_the_settings_name_at_the_time_of_reading(self):
        with workspace_temp_dir() as root:
            db_path = _gallery_with_columns(root, "output_files", [('[{"filename": "a.mp4"}]',)])

            with override_config(ORIGENERATOR_DB_PATH=db_path):
                found = origenerator_gallery.rows(("output_files",), optional=("remade_at",))

        assert found == [{"output_files": '[{"filename": "a.mp4"}]'}]


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
