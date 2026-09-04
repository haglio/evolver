import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import origenerator_metadata as om
from tests.temp_helpers import workspace_temp_dir

_SCHEMA = (
    "CREATE TABLE generations ("
    " prompt_id TEXT, positive_prompt TEXT, negative_prompt TEXT, seed INTEGER,"
    " params_json TEXT, output_files TEXT, created_at TEXT)"
)


def _row(prompt_id, *, pos=None, neg=None, seed=None, params=None,
         outputs=(), created=None):
    return {
        "prompt_id": prompt_id,
        "positive_prompt": pos,
        "negative_prompt": neg,
        "seed": seed,
        "params_json": json.dumps(params or {}),
        "output_files": json.dumps(
            [{"filename": name, "subfolder": "video", "type": "output"} for name in outputs]
        ),
        "created_at": created,
    }


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    conn.executemany(
        "INSERT INTO generations (prompt_id, positive_prompt, negative_prompt,"
        " seed, params_json, output_files, created_at)"
        " VALUES (:prompt_id, :positive_prompt, :negative_prompt, :seed,"
        " :params_json, :output_files, :created_at)",
        rows,
    )
    conn.commit()
    conn.close()


def _no_probe():
    """Patch away ffprobe so resolution is omitted (temp files aren't real videos)."""
    return patch("tasks.origenerator_metadata.video_dimensions", return_value=None)


class TestBuildMetadata(unittest.TestCase):
    def test_video_block_from_matching_row(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [
                _row("vid-1", pos="a woman dancing", seed=42,
                     params={"unet_high": "wan2.2_i2v_high_noise.gguf"},
                     outputs=["wan22_i2v_00001_.mp4"], created="2026-03-28 20:58:31"),
            ])
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)
        self.assertEqual(payload, {
            "video": {
                "prompt": "a woman dancing",
                "model": "wan2.2_i2v_high_noise",
                "seed": "42",
                "created": "2026-03-28",
            }
        })

    def test_resolves_source_image_block(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [
                _row("img-1", pos="portrait of a woman", neg="blurry", seed=7,
                     params={"checkpoint": "reapony_v80.safetensors"},
                     outputs=["wan22_t2i_00005_.png"], created="2026-03-27 10:00:00"),
                _row("vid-1", pos="she turns around", seed=42,
                     params={"unet_high": "wan_high.gguf",
                             "input_image": "wan22_t2i_00005_.png [output]"},
                     outputs=["wan22_i2v_00009_.mp4"], created="2026-03-28 12:00:00"),
            ])
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00009_.mp4"), db_path=db)
        self.assertEqual(payload["video"]["prompt"], "she turns around")
        self.assertEqual(payload["source_image"], {
            "positive_prompt": "portrait of a woman",
            "negative_prompt": "blurry",
            "model": "reapony_v80",
            "seed": "7",
            "created": "2026-03-27",
        })

    def test_no_source_image_when_input_image_unmatched(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [
                _row("vid-1", pos="a scene", seed=1,
                     params={"input_image": "some_dropped_photo.png"},
                     outputs=["wan22_i2v_00001_.mp4"]),
            ])
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)
        self.assertNotIn("source_image", payload)

    def test_strips_export_uniquifier_when_matching(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [
                _row("vid-1", pos="a scene", outputs=["wan22_i2v_00001_.mp4"]),
            ])
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00001_ (2).mp4"), db_path=db)
        self.assertEqual(payload["video"]["prompt"], "a scene")

    def test_raises_when_no_row_matches(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", outputs=["other.mp4"])])
            with _no_probe(), self.assertRaises(LookupError):
                om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)

    def test_raises_when_db_missing(self):
        with workspace_temp_dir() as root, self.assertRaises(FileNotFoundError):
            om.build_metadata(Path("x.mp4"), db_path=root / "nope.db")

    def test_includes_resolution_and_aspect_from_probe(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", pos="a scene", outputs=["wan22_i2v_00001_.mp4"])])
            with patch("tasks.origenerator_metadata.video_dimensions", return_value=(832, 480)):
                payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)
        self.assertEqual(payload["video"]["resolution"], "832x480")
        self.assertEqual(payload["video"]["aspect_ratio"], "16:9")

    def test_omits_empty_fields(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", outputs=["wan22_i2v_00001_.mp4"])])
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)
        # No prompt, no seed, no model, no created -> an empty video block, not keys with "".
        self.assertEqual(payload, {"video": {}})


class TestModelLabel(unittest.TestCase):
    def test_prefers_unet_high_and_strips_extension(self):
        self.assertEqual(om._model_label({"unet_high": "wan_high.gguf", "unet_low": "wan_low.gguf"}),
                         "wan_high")

    def test_flux_unet(self):
        self.assertEqual(om._model_label({"unet": "flux1-dev.safetensors"}), "flux1-dev")

    def test_sdxl_checkpoint_with_path(self):
        self.assertEqual(om._model_label({"checkpoint": "sub\\reapony_v80.safetensors"}), "reapony_v80")

    def test_empty_when_no_model_key(self):
        self.assertEqual(om._model_label({"steps": 8}), "")


class TestAspectRatio(unittest.TestCase):
    def test_snaps_landscape(self):
        self.assertEqual(om._aspect_ratio(832, 480), "16:9")

    def test_snaps_portrait(self):
        self.assertEqual(om._aspect_ratio(480, 832), "9:16")

    def test_snaps_square(self):
        self.assertEqual(om._aspect_ratio(624, 624), "1:1")

    def test_reduces_uncommon_ratio(self):
        self.assertEqual(om._aspect_ratio(1000, 300), "10:3")

    def test_empty_for_degenerate(self):
        self.assertEqual(om._aspect_ratio(0, 480), "")


class TestFrameName(unittest.TestCase):
    def test_strips_output_annotation_and_lowercases(self):
        self.assertEqual(om._frame_name("Sub/Wan22_T2I_00005_.PNG [output]"), "wan22_t2i_00005_.png")

    def test_bare_filename(self):
        self.assertEqual(om._frame_name("a.mp4"), "a.mp4")

    def test_empty(self):
        self.assertEqual(om._frame_name(None), "")


if __name__ == "__main__":
    unittest.main()
