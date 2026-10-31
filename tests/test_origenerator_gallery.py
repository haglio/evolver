from __future__ import annotations

import json
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


def _generated_fps_published_in(document: str) -> Fraction | None:
    with workspace_temp_dir() as checkout:
        (checkout / origenerator_gallery.PUBLISHED).write_text(document, encoding="utf-8")
        return origenerator_gallery.generated_fps(checkout)


if __name__ == "__main__":
    unittest.main()
