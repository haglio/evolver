"""The document this repo publishes about its pipeline, held against the config.

Origenerator hands clips to this pipeline by copying a file into one folder and
reads the upscale back out of another, and it cannot import this repo -- so it
had both paths and the half-written-file marker written out on its own side.
Renaming a folder here left it dropping clips where nothing ingests them, with
both suites green.

``evolver_contract.json`` at the checkout root is how those names travel now.
These hold the document to what this repo actually reads and writes.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import config
from tests.temp_helpers import workspace_temp_dir
from util import media_files
from util import pipeline_contract as contract

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document() -> dict:
    return json.loads(contract.contract_path(REPO_ROOT).read_text(encoding="utf-8"))


class PublishedDocument(unittest.TestCase):
    def test_the_tracked_copy_is_what_publishing_writes(self):
        """Run ``util.pipeline_contract.publish()`` when this fails: a document
        that has drifted from this module tells a sender something untrue."""
        tracked = contract.contract_path(REPO_ROOT)

        with workspace_temp_dir() as root:
            self.assertEqual(contract.publish(root).read_text(encoding="utf-8"),
                             tracked.read_text(encoding="utf-8"))

    def test_each_folder_it_names_is_the_one_this_repo_uses(self):
        """Library-relative, because the library root is private and the two
        apps resolve it from their own overlays."""
        document = _document()

        self.assertEqual(
            {name: config.BASE_DIR / Path(value)
             for name, value in document["library_relative"].items()},
            {"inbox_dir": config.INBOX_DIR,
             "upscaled_dir": config.OUT_UPSCALED_DIR},
        )

    def test_a_name_carrying_the_marker_is_one_this_repo_refuses_to_ingest(self):
        """The whole point of the marker: a copy still being written must not be
        read as a finished video."""
        marker = _document()["partial_marker"]

        self.assertTrue(media_files.is_partial_path(Path(f"a-clip{marker}mp4")))
        self.assertFalse(media_files.is_partial_path(Path("a-clip.mp4")))


if __name__ == "__main__":
    unittest.main()
