import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backfill import thumbnails
from tests.temp_helpers import override_config, workspace_temp_dir


class TestExampleClips(unittest.TestCase):
    def _tree(self, root):
        ai = root / "AI"
        return ai, ai / "2_outbox" / "upscaled_by_orientation", root / "metadata"

    def _video(self, upscaled, orient, source, name):
        video = upscaled / orient / source / name
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"video")
        return video

    def _sidecar(self, metadata, orient, source, stem, action):
        path = metadata / "AI" / "2_outbox" / "upscaled_by_orientation" / orient / source / f"{stem}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"video": {"action": action}}), encoding="utf-8")

    def test_collects_one_labeled_clip_per_action(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._video(upscaled, "portrait", "provider2", "a_topaz.mp4")
            self._sidecar(metadata, "portrait", "provider2", "a_topaz", "Side Gamma")

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(thumbnails.example_clips(), {"Side Gamma": video})

    def test_an_unlabeled_clip_contributes_no_example(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            self._video(upscaled, "portrait", "provider2", "a_topaz.mp4")  # no sidecar

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(thumbnails.example_clips(), {})

    def test_a_scraped_source_is_a_valid_example(self):
        """Unlike the work queue, the gallery welcomes already-labeled scraped clips."""
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            video = self._video(upscaled, "landscape", "provider", "b_topaz.mp4")
            self._sidecar(metadata, "landscape", "provider", "b_topaz", "POV Epsilon")

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(thumbnails.example_clips(), {"POV Epsilon": video})

    def test_the_first_clip_found_wins_for_an_action(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata = self._tree(root)
            first = self._video(upscaled, "portrait", "provider2", "a_topaz.mp4")
            self._video(upscaled, "portrait", "provider2", "z_topaz.mp4")
            self._sidecar(metadata, "portrait", "provider2", "a_topaz", "Side Alpha")
            self._sidecar(metadata, "portrait", "provider2", "z_topaz", "Side Alpha")

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata):
                self.assertEqual(thumbnails.example_clips(), {"Side Alpha": first})


class TestThumbnailCachePath(unittest.TestCase):
    def test_slugifies_the_action_into_a_stable_filename(self):
        with override_config(BACKFILL_THUMBNAIL_DIR=Path("/cache")):
            self.assertEqual(thumbnails.thumbnail_cache_path("POV Gamma"), Path("/cache/pov_gamma.jpg"))

    def test_the_same_action_always_maps_to_the_same_file(self):
        with override_config(BACKFILL_THUMBNAIL_DIR=Path("/cache")):
            self.assertEqual(
                thumbnails.thumbnail_cache_path("Side Beta Gamma"),
                thumbnails.thumbnail_cache_path("Side Beta Gamma"),
            )


class TestBuildThumbnails(unittest.TestCase):
    def test_extracts_and_yields_each_example(self):
        examples = {"Side Gamma": Path("a.mp4"), "POV Alpha": Path("b.mp4")}
        calls = []

        def extract(clip, dest):
            calls.append((clip, dest))
            return True

        result = list(thumbnails.build_thumbnails(examples, extract, lambda a: Path(f"/c/{a}.jpg")))

        self.assertEqual(
            result,
            [("Side Gamma", Path("/c/Side Gamma.jpg")), ("POV Alpha", Path("/c/POV Alpha.jpg"))],
        )
        self.assertEqual(calls[0], (Path("a.mp4"), Path("/c/Side Gamma.jpg")))

    def test_a_cached_thumbnail_is_reused_without_extracting(self):
        with workspace_temp_dir() as root:
            cached = root / "side_gamma.jpg"
            cached.write_bytes(b"img")
            extracted = []

            result = list(
                thumbnails.build_thumbnails(
                    {"Side Gamma": Path("a.mp4")},
                    lambda clip, dest: extracted.append(dest) or True,
                    lambda action: cached,
                )
            )

            self.assertEqual(result, [("Side Gamma", cached)])
            self.assertEqual(extracted, [])  # a cache hit never shells out to ffmpeg

    def test_an_extraction_failure_skips_that_action(self):
        examples = {"Good": Path("g.mp4"), "Bad": Path("b.mp4")}

        result = list(
            thumbnails.build_thumbnails(
                examples, lambda clip, dest: clip == Path("g.mp4"), lambda a: Path(f"/c/{a}.jpg")
            )
        )

        self.assertEqual(result, [("Good", Path("/c/Good.jpg"))])


class TestExtractFrame(unittest.TestCase):
    def test_runs_ffmpeg_at_a_fraction_of_the_duration(self):
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            def fake_run(argv, **kwargs):
                dest.write_bytes(b"img")  # ffmpeg wrote the frame
                return SimpleNamespace(returncode=0)

            with patch("backfill.thumbnails.duration_seconds", return_value=10.0), \
                 patch("backfill.thumbnails.subprocess.run", side_effect=fake_run) as run:
                ok = thumbnails.extract_frame(Path("clip.mp4"), dest, at_fraction=0.4)

            self.assertTrue(ok)
            argv = run.call_args[0][0]
            self.assertEqual(argv[argv.index("-ss") + 1], "4.000")
            self.assertIn(str(dest), argv)

    def test_seeks_to_zero_when_the_duration_is_unknown(self):
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            def fake_run(argv, **kwargs):
                dest.write_bytes(b"img")
                return SimpleNamespace(returncode=0)

            with patch("backfill.thumbnails.duration_seconds", return_value=None), \
                 patch("backfill.thumbnails.subprocess.run", side_effect=fake_run) as run:
                thumbnails.extract_frame(Path("clip.mp4"), dest)

            argv = run.call_args[0][0]
            self.assertEqual(argv[argv.index("-ss") + 1], "0.000")

    def test_returns_false_when_ffmpeg_fails(self):
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"
            with patch("backfill.thumbnails.duration_seconds", return_value=10.0), \
                 patch("backfill.thumbnails.subprocess.run", return_value=SimpleNamespace(returncode=1)):
                self.assertFalse(thumbnails.extract_frame(Path("clip.mp4"), dest))


if __name__ == "__main__":
    unittest.main()
