from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backfill import thumbnails
from backfill.queue import library_scan
from backfill.vocabulary import Act
from tests.temp_helpers import library_tree, override_config, workspace_temp_dir
from tests.vocabulary_support import vocabulary_of

VOCABULARY = vocabulary_of(Act("alpha", "Alpha"), Act("beta", "Beta"), Act("gamma", "Gamma"))

# Fabricated: a real pin names a video inside the library, which is why the pins
# moved to the git-ignored overlay in the first place. The button label is one the
# act table above produces.
PINNED_BUTTON = "Side Gamma"
PINNED_ID = "11111111-2222-3333-4444-555555555555"


class TestExampleVideos(unittest.TestCase):
    def _tag(self, lib, orient, source, stem, action):
        lib.sidecar(orient, source, stem, {"video": {"action": action}})

    def _examples(self, vocabulary=VOCABULARY):
        return thumbnails.example_videos(vocabulary, library_scan())

    def test_collects_one_labeled_video_per_action(self):
        with library_tree() as lib:
            video = lib.video("portrait", "provider2", "a_topaz.mp4")
            self._tag(lib, "portrait", "provider2", "a_topaz", "Side Beta")

            assert self._examples() == {"Side Beta": video}

    def test_the_examples_are_for_the_buttons_of_the_vocabulary_handed_in(self):
        with library_tree() as lib:
            video = lib.video("portrait", "provider2", "k_topaz.mp4")
            self._tag(lib, "portrait", "provider2", "k_topaz", "Side Kappa")

            assert self._examples(vocabulary_of(Act("kappa", "Kappa"))) == {"Side Kappa": video}
            assert self._examples(VOCABULARY) == {}

    def test_an_unlabeled_video_contributes_no_example(self):
        with library_tree() as lib:
            lib.video("portrait", "provider2", "a_topaz.mp4")

            assert self._examples() == {}

    def test_a_scraped_source_is_a_valid_example(self):
        with library_tree() as lib:
            video = lib.video("landscape", "provider", "b_topaz.mp4")
            self._tag(lib, "landscape", "provider", "b_topaz", "XYZ Gamma")

            assert self._examples() == {"XYZ Gamma": video}

    def test_the_first_video_found_wins_for_an_action(self):
        with library_tree() as lib:
            first = lib.video("portrait", "provider2", "a_topaz.mp4")
            lib.video("portrait", "provider2", "z_topaz.mp4")
            self._tag(lib, "portrait", "provider2", "a_topaz", "Side Alpha")
            self._tag(lib, "portrait", "provider2", "z_topaz", "Side Alpha")

            assert self._examples() == {"Side Alpha": first}

    def test_a_compound_tag_illustrates_each_of_its_parts(self):
        with library_tree() as lib:
            video = lib.video("portrait", "provider", "c_topaz.mp4")
            self._tag(lib, "portrait", "provider", "c_topaz", "XYZ Gamma, Side Alpha")

            examples = self._examples()

            assert examples["XYZ Gamma"] == video
            assert examples["Side Alpha"] == video

    def test_a_curated_pin_supplies_a_button_the_library_never_tags(self):
        with library_tree() as lib:
            pinned = lib.video("portrait", "provider", f"{PINNED_ID}_topaz.mp4")

            with override_config(CURATED_EXAMPLES={PINNED_BUTTON: PINNED_ID}):
                assert self._examples() == {PINNED_BUTTON: pinned}

    def test_a_curated_pin_wins_over_an_auto_match(self):
        with library_tree() as lib:
            pinned = lib.video("portrait", "provider", f"{PINNED_ID}_topaz.mp4")
            lib.video("portrait", "provider2", "auto_topaz.mp4")
            self._tag(lib, "portrait", "provider2", "auto_topaz", PINNED_BUTTON)

            with override_config(CURATED_EXAMPLES={PINNED_BUTTON: PINNED_ID}):
                assert self._examples()[PINNED_BUTTON] == pinned

    def test_a_pin_naming_a_video_the_library_does_not_hold_falls_through(self):
        with library_tree() as lib:
            auto = lib.video("portrait", "provider2", "auto_topaz.mp4")
            self._tag(lib, "portrait", "provider2", "auto_topaz", PINNED_BUTTON)

            with override_config(CURATED_EXAMPLES={PINNED_BUTTON: "not-in-this-library"}):
                assert self._examples()[PINNED_BUTTON] == auto

    def test_no_pins_at_all_leaves_every_button_to_the_automatic_match(self):
        with library_tree() as lib:
            auto = lib.video("portrait", "provider2", "auto_topaz.mp4")
            self._tag(lib, "portrait", "provider2", "auto_topaz", PINNED_BUTTON)

            with override_config(CURATED_EXAMPLES={}):
                assert self._examples() == {PINNED_BUTTON: auto}


class TestThumbnailCachePath(unittest.TestCase):
    def test_slugifies_the_action_into_a_stable_filename(self):
        with override_config(BACKFILL_THUMBNAIL_DIR=Path("/cache")):
            assert thumbnails.thumbnail_cache_path("XYZ Beta") == Path("/cache/xyz_beta.jpg")


class TestBuildThumbnails(unittest.TestCase):
    def test_extracts_and_yields_each_example(self):
        examples = {"Side Beta": Path("a.mp4"), "XYZ Alpha": Path("b.mp4")}
        calls = []

        def extract(video, dest):
            calls.append((video, dest))
            return True

        result = list(thumbnails.build_thumbnails(examples, extract, lambda a: Path(f"/c/{a}.jpg")))

        assert result == [("Side Beta", Path("/c/Side Beta.jpg")), ("XYZ Alpha", Path("/c/XYZ Alpha.jpg"))]
        assert calls[0] == (Path("a.mp4"), Path("/c/Side Beta.jpg"))

    def test_a_cached_thumbnail_is_reused_without_extracting(self):
        with workspace_temp_dir() as root:
            cached = root / "side_beta.jpg"
            cached.write_bytes(b"img")
            extracted = []

            result = list(
                thumbnails.build_thumbnails(
                    {"Side Beta": Path("a.mp4")},
                    lambda video, dest: extracted.append(dest) or True,
                    lambda action: cached,
                )
            )

            assert result == [("Side Beta", cached)]
            assert extracted == []  # a cache hit never shells out to ffmpeg

    def test_an_extraction_failure_skips_that_action(self):
        examples = {"Good": Path("g.mp4"), "Bad": Path("b.mp4")}

        result = list(
            thumbnails.build_thumbnails(
                examples, lambda video, dest: video == Path("g.mp4"), lambda a: Path(f"/c/{a}.jpg")
            )
        )

        assert result == [("Good", Path("/c/Good.jpg"))]


class TestExtractFrame(unittest.TestCase):
    def test_runs_ffmpeg_at_a_fraction_of_the_duration(self):
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            def fake_run(argv, **kwargs):
                dest.write_bytes(b"img")  # ffmpeg wrote the frame
                return SimpleNamespace(returncode=0)

            with patch("backfill.thumbnails.duration_seconds", return_value=10.0), \
                 patch("backfill.thumbnails.subprocess.run", side_effect=fake_run) as run:
                ok = thumbnails.extract_frame(Path("video.mp4"), dest)

            assert ok
            argv = run.call_args[0][0]
            assert argv[argv.index("-ss") + 1] == "4.000"
            assert str(dest) in argv

    def test_scales_to_the_one_thumbnail_height(self):
        assert "height" not in inspect.signature(thumbnails.extract_frame).parameters
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            def fake_run(argv, **kwargs):
                dest.write_bytes(b"img")
                return SimpleNamespace(returncode=0)

            with patch("backfill.thumbnails.duration_seconds", return_value=10.0), \
                 patch("backfill.thumbnails.subprocess.run", side_effect=fake_run) as run:
                thumbnails.extract_frame(Path("video.mp4"), dest)

            argv = run.call_args[0][0]
            assert argv[argv.index("-vf") + 1] == f"scale=-2:{thumbnails._THUMBNAIL_HEIGHT}"

    def test_seeks_to_zero_when_the_duration_is_unknown(self):
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            def fake_run(argv, **kwargs):
                dest.write_bytes(b"img")
                return SimpleNamespace(returncode=0)

            with patch("backfill.thumbnails.duration_seconds", return_value=None), \
                 patch("backfill.thumbnails.subprocess.run", side_effect=fake_run) as run:
                thumbnails.extract_frame(Path("video.mp4"), dest)

            argv = run.call_args[0][0]
            assert argv[argv.index("-ss") + 1] == "0.000"

    def test_a_frame_ffmpeg_could_not_write_is_reported_as_not_extracted(self):
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"
            with patch("backfill.thumbnails.duration_seconds", return_value=10.0), \
                 patch("backfill.thumbnails.subprocess.run", return_value=SimpleNamespace(returncode=1)):
                assert not thumbnails.extract_frame(Path("video.mp4"), dest)

    def test_a_missing_probe_leaves_the_button_text_only_rather_than_crashing(self):
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            with patch("backfill.thumbnails.duration_seconds",
                       side_effect=FileNotFoundError("ffprobe")):
                assert not thumbnails.extract_frame(Path("video.mp4"), dest)

    def test_a_missing_encoder_leaves_it_text_only_too(self):
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            with patch("backfill.thumbnails.duration_seconds", return_value=10.0), \
                 patch("backfill.thumbnails.subprocess.run",
                       side_effect=FileNotFoundError("ffmpeg")):
                assert not thumbnails.extract_frame(Path("video.mp4"), dest)


if __name__ == "__main__":
    unittest.main()
