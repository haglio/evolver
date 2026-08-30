import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backfill import thumbnails
from tests.temp_helpers import library_tree, override_config, workspace_temp_dir


class TestExampleClips(unittest.TestCase):
    def _tag(self, lib, orient, source, stem, action):
        lib.sidecar(orient, source, stem, {"video": {"action": action}})

    def test_collects_one_labeled_clip_per_action(self):
        with library_tree() as lib:
            video = lib.video("portrait", "provider2", "a_topaz.mp4")
            self._tag(lib, "portrait", "provider2", "a_topaz", "Side Beta")

            self.assertEqual(thumbnails.example_clips(), {"Side Beta": video})

    def test_an_unlabeled_clip_contributes_no_example(self):
        with library_tree() as lib:
            lib.video("portrait", "provider2", "a_topaz.mp4")  # no sidecar

            self.assertEqual(thumbnails.example_clips(), {})

    def test_a_scraped_source_is_a_valid_example(self):
        """Unlike the work queue, the gallery welcomes already-labeled scraped clips."""
        with library_tree() as lib:
            video = lib.video("landscape", "provider", "b_topaz.mp4")
            self._tag(lib, "landscape", "provider", "b_topaz", "POV Gamma")

            self.assertEqual(thumbnails.example_clips(), {"POV Gamma": video})

    def test_the_first_clip_found_wins_for_an_action(self):
        with library_tree() as lib:
            first = lib.video("portrait", "provider2", "a_topaz.mp4")
            lib.video("portrait", "provider2", "z_topaz.mp4")
            self._tag(lib, "portrait", "provider2", "a_topaz", "Side Alpha")
            self._tag(lib, "portrait", "provider2", "z_topaz", "Side Alpha")

            self.assertEqual(thumbnails.example_clips(), {"Side Alpha": first})

    def test_a_compound_tag_illustrates_each_of_its_parts(self):
        with library_tree() as lib:
            video = lib.video("portrait", "provider", "c_topaz.mp4")
            self._tag(lib, "portrait", "provider", "c_topaz", "POV Gamma, Side Alpha")

            examples = thumbnails.example_clips()

            self.assertEqual(examples["POV Gamma"], video)
            self.assertEqual(examples["Side Alpha"], video)

    def test_a_curated_pin_supplies_a_tile_the_library_never_tags(self):
        tile, clip_id = next(iter(thumbnails.CURATED_EXAMPLES.items()))
        with library_tree() as lib:
            pinned = lib.video("portrait", "provider", f"{clip_id}_topaz.mp4")

            self.assertEqual(thumbnails.example_clips(), {tile: pinned})

    def test_a_curated_pin_wins_over_an_auto_match(self):
        tile, clip_id = next(iter(thumbnails.CURATED_EXAMPLES.items()))
        with library_tree() as lib:
            pinned = lib.video("portrait", "provider", f"{clip_id}_topaz.mp4")
            lib.video("portrait", "provider2", "auto_topaz.mp4")
            self._tag(lib, "portrait", "provider2", "auto_topaz", tile)

            self.assertEqual(thumbnails.example_clips()[tile], pinned)


class TestThumbnailCachePath(unittest.TestCase):
    def test_slugifies_the_action_into_a_stable_filename(self):
        with override_config(BACKFILL_THUMBNAIL_DIR=Path("/cache")):
            self.assertEqual(thumbnails.thumbnail_cache_path("POV Beta"), Path("/cache/pov_beta.jpg"))


class TestBuildThumbnails(unittest.TestCase):
    def test_extracts_and_yields_each_example(self):
        examples = {"Side Beta": Path("a.mp4"), "POV Alpha": Path("b.mp4")}
        calls = []

        def extract(clip, dest):
            calls.append((clip, dest))
            return True

        result = list(thumbnails.build_thumbnails(examples, extract, lambda a: Path(f"/c/{a}.jpg")))

        self.assertEqual(
            result,
            [("Side Beta", Path("/c/Side Beta.jpg")), ("POV Alpha", Path("/c/POV Alpha.jpg"))],
        )
        self.assertEqual(calls[0], (Path("a.mp4"), Path("/c/Side Beta.jpg")))

    def test_a_cached_thumbnail_is_reused_without_extracting(self):
        with workspace_temp_dir() as root:
            cached = root / "side_beta.jpg"
            cached.write_bytes(b"img")
            extracted = []

            result = list(
                thumbnails.build_thumbnails(
                    {"Side Beta": Path("a.mp4")},
                    lambda clip, dest: extracted.append(dest) or True,
                    lambda action: cached,
                )
            )

            self.assertEqual(result, [("Side Beta", cached)])
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
                # No at_fraction: the default IS the tuned value, chosen to
                # sample past a clip's title card, and passing it explicitly
                # left the constant free to drift (audit probe 28 moved it to
                # 0.9 with the suite green).
                ok = thumbnails.extract_frame(Path("clip.mp4"), dest)

            self.assertTrue(ok)
            argv = run.call_args[0][0]
            self.assertEqual(argv[argv.index("-ss") + 1], "4.000")
            self.assertIn(str(dest), argv)

    def test_scales_to_the_one_thumbnail_height(self):
        """Like at_fraction, the height is the tuned value and no caller names
        it — the grid draws every tile at one size."""
        assert "height" not in inspect.signature(thumbnails.extract_frame).parameters
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            def fake_run(argv, **kwargs):
                dest.write_bytes(b"img")
                return SimpleNamespace(returncode=0)

            with patch("backfill.thumbnails.duration_seconds", return_value=10.0), \
                 patch("backfill.thumbnails.subprocess.run", side_effect=fake_run) as run:
                thumbnails.extract_frame(Path("clip.mp4"), dest)

            argv = run.call_args[0][0]
            self.assertEqual(argv[argv.index("-vf") + 1], f"scale=-2:{thumbnails._THUMBNAIL_HEIGHT}")

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

    def test_a_missing_probe_leaves_the_tile_text_only_rather_than_crashing(self):
        """duration_seconds sat ABOVE the try that exists to survive a missing
        binary, so a FileNotFoundError from it escaped extract_frame, escaped
        the build_thumbnails generator and took backfill_app.main() down -- and
        under pythonw.exe there is no console, so the tool simply never
        appeared."""
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            with patch("backfill.thumbnails.duration_seconds",
                       side_effect=FileNotFoundError("ffprobe")):
                self.assertFalse(thumbnails.extract_frame(Path("clip.mp4"), dest))

    def test_a_missing_encoder_leaves_it_text_only_too(self):
        with workspace_temp_dir() as root:
            dest = root / "out.jpg"

            with patch("backfill.thumbnails.duration_seconds", return_value=10.0), \
                 patch("backfill.thumbnails.subprocess.run",
                       side_effect=FileNotFoundError("ffmpeg")):
                self.assertFalse(thumbnails.extract_frame(Path("clip.mp4"), dest))


if __name__ == "__main__":
    unittest.main()
