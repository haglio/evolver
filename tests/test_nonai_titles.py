from __future__ import annotations

import unittest
from pathlib import Path

from tasks import nonai_titles
from tests.temp_helpers import override_config, workspace_temp_dir
from util import sidecar


def _touch(path: Path, body: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def _library(root: Path) -> tuple[Path, Path, Path]:
    """A (video_library, non_AI, metadata) triple mirroring the real layout."""
    video_lib = root / "videos"
    non_ai = video_lib / "2D" / "non_AI"
    metadata = root / "metadata"
    return video_lib, non_ai, metadata


def _record(video: Path, payload: dict) -> None:
    path = sidecar.sidecar_path(video)
    path.parent.mkdir(parents=True, exist_ok=True)
    sidecar.update(path, lambda existing: {**existing, **payload})


def _title_of(video: Path) -> str:
    return sidecar.read(sidecar.sidecar_path(video)).get("title", "")


class TestNonAiTitles(unittest.TestCase):
    def test_a_clip_is_titled_by_the_pair_recorded_for_it(self):
        """The record carries the movie's own punctuation, which the filename had
        to drop -- Windows will not hold a colon in one."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                clip = _touch(non_ai / "larkin" / "3_good_to_go"
                              / "Jane Doe - Alpha Study Part Two.mp4")
                _record(clip, {"clip": {"performer": "Jane Doe",
                                        "source": "Alpha Study: Part Two"}})

                nonai_titles.run()

                self.assertEqual(_title_of(clip), "Jane Doe - Alpha Study: Part Two")

    def test_a_scene_takes_the_name_of_the_clip_matched_inside_it(self):
        """The scene was saved under whatever the download called it; the clip
        carved from it is the only thing that knows the movie and who is in it,
        and the clip-match batch proved the pairing on the frames."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                scene = _touch(non_ai / "larkin" / "0 unsorted" / "Jane-Doe_540-hQ2vLm8t.mp4")
                _record(scene, {"version": {"group": "Jane-Doe_540-hQ2vLm8t"}})
                clip = _touch(non_ai / "larkin" / "3_good_to_go"
                              / "Jane Doe - Alpha Study 3.mp4")
                _record(clip, {"version": {"group": "Jane Doe - Alpha Study 3"},
                               "clip": {"performer": "Jane Doe", "source": "Alpha Study 3",
                                        "full_video": str(scene)}})

                nonai_titles.run()

                self.assertEqual(_title_of(scene), "Jane Doe - Alpha Study 3")

    def test_the_scenes_name_reaches_the_rendition_that_was_not_matched(self):
        """The batch records its match against the one file it searched, while
        the apps play whichever rendition they judge best -- so the name is held
        against the family, not the path."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                matched = _touch(non_ai / "larkin" / "0 unsorted" / "Jane-Doe_540-hQ2vLm8t.mp4")
                upscale = _touch(non_ai / "larkin" / "3_good_to_go" / "processed"
                                 / "Jane-Doe_540-hQ2vLm8t_apo8_iris2.mp4")
                for rendition in (matched, upscale):
                    _record(rendition, {"version": {"group": "Jane-Doe_540-hQ2vLm8t"}})
                clip = _touch(non_ai / "larkin" / "3_good_to_go"
                              / "Jane Doe - Alpha Study 3.mp4")
                _record(clip, {"version": {"group": "Jane Doe - Alpha Study 3"},
                               "clip": {"performer": "Jane Doe", "source": "Alpha Study 3",
                                        "full_video": str(matched)}})

                nonai_titles.run()

                self.assertEqual(_title_of(upscale), "Jane Doe - Alpha Study 3")

    def test_a_video_nothing_names_is_left_without_one(self):
        """Its readers fall back to the filename, which is what they always did."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                lone = _touch(non_ai / "larkin" / "0 unsorted" / "Ada-Roe-1.mp4")
                _record(lone, {"version": {"group": "Ada-Roe-1"}})

                result = nonai_titles.run()

                self.assertNotIn("title", sidecar.read(sidecar.sidecar_path(lone)))
                self.assertEqual((result.titled, result.videos), (0, 1))

    def test_a_name_that_no_longer_holds_is_taken_back_off(self):
        """A backfill that never ends has to be able to correct itself: strike
        the clip record and the name it justified goes with it, rather than
        standing forever over a video nothing says that about."""
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata
            ):
                video = _touch(non_ai / "larkin" / "0 unsorted" / "Ada-Roe-1.mp4")
                _record(video, {"version": {"group": "Ada-Roe-1"},
                                "title": "Jane Doe - Alpha Study 3"})

                nonai_titles.run()

                self.assertNotIn("title", sidecar.read(sidecar.sidecar_path(video)))

    def test_it_leaves_the_excluded_bucket_alone(self):
        with workspace_temp_dir() as root:
            video_lib, non_ai, metadata = _library(root)
            with override_config(
                VIDEO_LIBRARY_DIR=video_lib, NON_AI_DIR=non_ai, METADATA_DIR=metadata,
                NONAI_EXCLUDED_BUCKETS={"actually_AI_but_funscripted"},
            ):
                clip = _touch(non_ai / "actually_AI_but_funscripted" / "landscape" / "x.mp4")

                nonai_titles.run()

                self.assertFalse(sidecar.sidecar_path(clip).exists())
