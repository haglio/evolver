from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from app_support import provenance

from tasks import origenerator_metadata as om
from tests.temp_helpers import workspace_temp_dir
from util.provenance import METHOD, METHOD_VERSION

_SCHEMA = (
    "CREATE TABLE generations ("
    " prompt_id TEXT, workflow_name TEXT, workflow_version TEXT,"
    " positive_prompt TEXT, negative_prompt TEXT, seed INTEGER,"
    " params_json TEXT, output_files TEXT, created_at TEXT)"
)


_ROW_DEFAULTS = {
    "workflow": "wan22_i2v", "version": "v001", "pos": None, "neg": None,
    "seed": None, "params": None, "outputs": (), "created": None,
}


def _row(prompt_id, **given):
    unknown = given.keys() - _ROW_DEFAULTS.keys()
    if unknown:
        raise TypeError(f"unknown row field: {', '.join(sorted(unknown))}")
    fields = {**_ROW_DEFAULTS, **given}
    return {
        "prompt_id": prompt_id,
        "workflow_name": fields["workflow"],
        "workflow_version": fields["version"],
        "positive_prompt": fields["pos"],
        "negative_prompt": fields["neg"],
        "seed": fields["seed"],
        "params_json": json.dumps(fields["params"] or {}),
        "output_files": json.dumps(
            [{"filename": name, "subfolder": "video", "type": "output"}
             for name in fields["outputs"]]
        ),
        "created_at": fields["created"],
    }


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    conn.executemany(
        "INSERT INTO generations (prompt_id, workflow_name, workflow_version,"
        " positive_prompt, negative_prompt, seed, params_json, output_files, created_at)"
        " VALUES (:prompt_id, :workflow_name, :workflow_version, :positive_prompt,"
        " :negative_prompt, :seed, :params_json, :output_files, :created_at)",
        rows,
    )
    conn.commit()
    conn.close()


def _stamp_row(path, prompt_id, stamp):
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE generations ADD COLUMN provenance TEXT")
    conn.execute("UPDATE generations SET provenance = ? WHERE prompt_id = ?",
                 (json.dumps(stamp), prompt_id))
    conn.commit()
    conn.close()


def _no_probe():
    return patch("tasks.origenerator_metadata.video_dimensions", return_value=None)


class TestWhatMadeTheVideo(unittest.TestCase):
    def test_the_generation_s_workflow_and_its_version_are_recorded_as_what_made_it(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", workflow="wan22_i2v", version="v007",
                               outputs=["wan22_i2v_00001_.mp4"])])
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)

        assert payload["provenance"] == {"generation": {"schema": provenance.SCHEMA, "app": "origenerator", "app_commit": None, "app_dirty": None, METHOD: "wan22_i2v", METHOD_VERSION: "v007", "stamped_at": None}}

    def test_what_an_import_writes_in_place_of_a_workflow_is_recorded_as_unknown(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", workflow="unknown", version="imported",
                               outputs=["wan22_i2v_00001_.mp4"])])
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)

        generation = payload["provenance"]["generation"]
        assert (generation[METHOD], generation[METHOD_VERSION]) == (None, None)

    def test_a_record_the_gallery_keeps_of_its_own_is_carried_as_it_stands(self):
        its_own = {
            "schema": provenance.SCHEMA, "app": "origenerator",
            "app_commit": "0123abc", "app_dirty": False,
            METHOD: "wan22_i2v", METHOD_VERSION: "v007",
            "stamped_at": "2026-09-01T20:15:00+00:00",
        }
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", workflow="wan22_i2v", version="v007",
                               outputs=["wan22_i2v_00001_.mp4"])])
            _stamp_row(db, "vid-1", its_own)
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)

        assert payload["provenance"]["generation"] == its_own


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
        assert payload["video"] == {"prompt": "a woman dancing", "model": "wan2.2_i2v_high_noise", "seed": "42", "created": "2026-03-28"}

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
        assert payload["video"]["prompt"] == "she turns around"
        assert payload["source_image"] == {"positive_prompt": "portrait of a woman", "negative_prompt": "blurry", "model": "reapony_v80", "seed": "7", "created": "2026-03-27"}

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
        assert "source_image" not in payload

    def test_strips_export_uniquifier_when_matching(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [
                _row("vid-1", pos="a scene", outputs=["wan22_i2v_00001_.mp4"]),
            ])
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00001_ (2).mp4"), db_path=db)
        assert payload["video"]["prompt"] == "a scene"

    def test_raises_when_no_row_matches(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", outputs=["other.mp4"])])
            with _no_probe(), pytest.raises(LookupError):
                om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)

    def test_raises_when_db_missing(self):
        with workspace_temp_dir() as root, pytest.raises(FileNotFoundError):
            om.build_metadata(Path("x.mp4"), db_path=root / "nope.db")

    def test_includes_resolution_and_aspect_from_probe(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", pos="a scene", outputs=["wan22_i2v_00001_.mp4"])])
            with patch("tasks.origenerator_metadata.video_dimensions", return_value=(832, 480)):
                payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)
        assert payload["video"]["resolution"] == "832x480"
        assert payload["video"]["aspect_ratio"] == "16:9"

    def test_omits_empty_fields(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", outputs=["wan22_i2v_00001_.mp4"])])
            with _no_probe():
                payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=db)
        assert payload["video"] == {}


class TestModelLabel(unittest.TestCase):
    def test_prefers_unet_high_and_strips_extension(self):
        assert om._model_label({"unet_high": "wan_high.gguf", "unet_low": "wan_low.gguf"}) == "wan_high"

    def test_flux_unet(self):
        assert om._model_label({"unet": "flux1-dev.safetensors"}) == "flux1-dev"

    def test_sdxl_checkpoint_with_path(self):
        assert om._model_label({"checkpoint": "sub\\reapony_v80.safetensors"}) == "reapony_v80"

    def test_empty_when_no_model_key(self):
        assert om._model_label({"steps": 8}) == ""


class TestAspectRatio(unittest.TestCase):
    def test_snaps_landscape(self):
        assert om._aspect_ratio(832, 480) == "16:9"

    def test_snaps_portrait(self):
        assert om._aspect_ratio(480, 832) == "9:16"

    def test_snaps_square(self):
        assert om._aspect_ratio(624, 624) == "1:1"

    def test_reduces_uncommon_ratio(self):
        assert om._aspect_ratio(1000, 300) == "10:3"

    def test_empty_for_degenerate(self):
        assert om._aspect_ratio(0, 480) == ""


class TestFrameName(unittest.TestCase):
    def test_strips_output_annotation_and_lowercases(self):
        assert om._frame_name("Sub/Wan22_T2I_00005_.PNG [output]") == "wan22_t2i_00005_.png"

    def test_bare_filename(self):
        assert om._frame_name("a.mp4") == "a.mp4"

    def test_empty(self):
        assert om._frame_name(None) == ""


if __name__ == "__main__":
    unittest.main()


_WORDS_VIDEO = {"prompt": "a boat on a lake", "model": "Motion B", "seed": "7"}
_FRAME = "frame-one.jpg"


def _library_row(prompt_id, library_path, frame=_FRAME):
    return {**_row(prompt_id, params={"input_image": frame}),
            "output_files": json.dumps([{"filename": Path(library_path).name,
                                         "library_path": str(library_path)}])}


def _record_of(root, name, record):
    path = root / "metadata" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


class _ALibrary:
    def __init__(self, root):
        self.root = root
        self.db = root / "origenerator.db"

    def __enter__(self):
        videos = self.root / "videos"
        self._patches = [patch("config.VIDEO_LIBRARY_DIR", videos),
                         patch("config.VIDEO_SEARCH_ROOT", videos),
                         patch("config.METADATA_DIR", self.root / "metadata"),
                         _no_probe()]
        for one in self._patches:
            one.start()
        return self

    def __exit__(self, *_):
        for one in self._patches:
            one.stop()

    def with_rows(self, *rows):
        _make_db(self.db, list(rows))
        return self

    def t2v_video_and_its_frame(self):
        _record_of(self.root, "words-one", {"video": _WORDS_VIDEO})
        return (_row("frame-1", pos="the words of the frame", seed=3, outputs=[_FRAME]),
                _library_row("words-1", self.root / "videos" / "words-one.mp4"))


class TestAVideoMadeFromAT2VVideosStartingFrame(unittest.TestCase):
    def test_its_source_image_block_names_the_t2v_video_it_was_taken_from(self):
        with workspace_temp_dir() as root, _ALibrary(root) as library:
            frame, words = library.t2v_video_and_its_frame()
            library.with_rows(frame, words, _row("made-1", params={"input_image": _FRAME},
                                                 outputs=["wan22_i2v_00001_.mp4"]))
            payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=library.db)

        assert payload["source_image"]["frame_of_video"] == _WORDS_VIDEO
        assert payload["source_image"]["positive_prompt"] == "the words of the frame"

    def test_it_finds_the_t2v_video_through_any_file_of_the_frame(self):
        with workspace_temp_dir() as root, _ALibrary(root) as library:
            frame, words = library.t2v_video_and_its_frame()
            frame = {**frame, "output_files": json.dumps(
                [{"filename": _FRAME}, {"filename": "frame-one-enhanced.png"}])}
            library.with_rows(frame, words, _row("made-1", params={"input_image": "frame-one-enhanced.png"},
                                                 outputs=["wan22_i2v_00001_.mp4"]))
            payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=library.db)

        assert payload["source_image"]["frame_of_video"] == _WORDS_VIDEO

    def test_a_video_made_from_an_image_names_no_video(self):
        with workspace_temp_dir() as root, _ALibrary(root) as library:
            _record_of(root, "other-one", {"video": _WORDS_VIDEO,
                                           "source_image": {"positive_prompt": "its image"}})
            library.with_rows(_row("image-1", pos="an image", outputs=[_FRAME]),
                              _library_row("other-1", root / "videos" / "other-one.mp4"),
                              _row("made-1", params={"input_image": _FRAME},
                                   outputs=["wan22_i2v_00001_.mp4"]))
            payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=library.db)

        assert "frame_of_video" not in payload["source_image"]

    def test_a_video_kept_outside_the_library_names_no_video(self):
        with workspace_temp_dir() as root, _ALibrary(root) as library:
            library.with_rows(_row("image-1", pos="an image", outputs=[_FRAME]),
                              _library_row("other-1", root / "elsewhere" / "other-one.mp4"),
                              _row("made-1", params={"input_image": _FRAME},
                                   outputs=["wan22_i2v_00001_.mp4"]))
            payload = om.build_metadata(Path("wan22_i2v_00001_.mp4"), db_path=library.db)

        assert "frame_of_video" not in payload["source_image"]
