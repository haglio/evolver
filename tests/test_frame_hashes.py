from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from unittest.mock import patch

import numpy as np

from tests.product_sources import PROJECT_ROOT
from util import frame_hashes as fh
from util.frame_hashes import (
    LEAST_CONTENT_A_REAL_LETTERBOX_LEAVES,
    SAMPLE_HEIGHT,
    SAMPLE_WIDTH,
    align,
    content_crop_in,
    frame_hashes,
    locate,
)


def _hashes(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2**64, size=n, dtype=np.uint64)


class TestFrameHashes:
    def test_reading_relative_brightness_a_dimmer_copy_of_a_frame_hashes_the_same(self):
        rng = np.random.default_rng(3)
        frames = rng.integers(40, 200, size=(5, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)

        assert list(frame_hashes(frames - 20)) == list(frame_hashes(frames))

    def test_a_video_ffmpeg_could_not_read_hashes_to_nothing(self):
        nothing = np.empty((0, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)

        assert len(frame_hashes(nothing)) == 0
        assert align(frame_hashes(nothing), _hashes(400), fps=8.0) is None

    def test_different_frames_hash_differently(self):
        rng = np.random.default_rng(4)
        frames = rng.integers(0, 256, size=(20, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)

        assert len(set(frame_hashes(frames).tolist())) == 20


class TestContentCropIn:

    def _report(self, width: int, height: int, x: int = 0, y: int = 0) -> str:
        return (
            f"[Parsed_cropdetect_0 @ 000] x1:{x} x2:0 y1:{y} y2:0 w:{width} h:{height} "
            f"x:{x} y:{y} pts:1 t:0.04 limit:24 crop={width}:{height}:{x}:{y}"
        )

    def test_finds_the_content_inside_a_pillarboxed_frame(self):
        report = self._report(1440, 1080, x=240)

        assert content_crop_in([report], 1920, 1080) == (1440, 1080, 240, 0)

    def test_a_frame_with_no_bars_is_left_alone(self):
        report = self._report(1920, 1080)

        assert content_crop_in([report], 1920, 1080) is None

    def test_a_dark_moment_can_only_shrink_a_window_so_the_widest_wins(self):
        dark = self._report(600, 400, x=660, y=340)
        lit = self._report(1440, 1080, x=240)

        assert content_crop_in([dark, lit, dark], 1920, 1080) == (1440, 1080, 240, 0)

    def test_a_video_that_reads_as_nearly_all_black_is_left_alone(self):
        sliver = int(1080 * LEAST_CONTENT_A_REAL_LETTERBOX_LEAVES) - 20
        report = self._report(1920, sliver, y=(1080 - sliver) // 2)

        assert content_crop_in([report], 1920, 1080) is None

    def test_nothing_measured_means_nothing_cropped(self):
        assert content_crop_in(["ffmpeg version 7.1", ""], 1920, 1080) is None

    def test_the_rectangle_is_even_on_every_side(self):
        crop = content_crop_in([self._report(1437, 1077, x=241, y=1)], 1920, 1080)

        assert crop is not None
        assert not any(value % 2 for value in crop)

    def test_an_odd_rectangle_is_rounded_outward_to_stay_the_widest_reading(self):
        crop_width, crop_height, left, upper = content_crop_in(
            [self._report(1437, 1077, x=241, y=1)], 1920, 1080)

        assert (left, upper) <= (241, 1)
        assert (left + crop_width, upper + crop_height) >= (241 + 1437, 1 + 1077)


class TestContentCrop:
    def test_a_video_ffprobe_cannot_measure_is_not_cropped(self):
        with patch.object(fh.ffprobe, "video_dimensions", return_value=None):
            assert fh.content_crop(Path("gone.mp4")) is None

    def test_a_video_with_no_duration_is_not_cropped(self):
        with patch.object(fh.ffprobe, "video_dimensions", return_value=(1920, 1080)), \
             patch.object(fh.ffprobe, "duration_seconds", return_value=None):
            assert fh.content_crop(Path("gone.mp4")) is None


class TestSampleFrames:
    def _filters(self, crop) -> str:
        seen: dict[str, list[str]] = {}

        class _Finished:
            stdout = b""
            stderr = b""

        with patch.object(fh, "content_crop", lambda video: crop), \
             patch.object(fh.subprocess, "run",
                          lambda command, **kwargs: seen.update(command=command) or _Finished()):
            fh.sample_frames(Path("scene.mp4"), 8.0)
        command = seen["command"]
        return command[command.index("-vf") + 1]

    def test_the_bars_come_off_before_the_frame_is_scaled_down(self):
        assert self._filters((1440, 1080, 240, 0)) == (
            f"fps=8.0,crop=1440:1080:240:0,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area"
        )

    def test_a_video_with_no_bars_is_scaled_whole(self):
        assert self._filters(None) == (
            f"fps=8.0,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area"
        )

    def _decoded(self, run):
        with patch.object(fh, "content_crop", lambda video: None), \
             patch.object(fh.subprocess, "run", run), \
             patch.object(fh.log, "warning") as warning:
            frames = fh.sample_frames(Path("scene.mp4"), 8.0)
        return frames, warning

    def test_ffmpeg_decodes_below_normal_priority_so_whatever_he_is_doing_comes_first(self):
        seen = {}

        class _Finished:
            stdout = b""
            stderr = b""

        self._decoded(lambda command, **kwargs: seen.update(kwargs) or _Finished())

        assert seen["creationflags"] & subprocess.BELOW_NORMAL_PRIORITY_CLASS

    def test_a_file_ffmpeg_cannot_read_gives_no_frames_rather_than_stopping_the_batch(self):
        def refuses(command, **kwargs):
            raise subprocess.CalledProcessError(1, command, stderr=b"invalid data")

        frames, _warning = self._decoded(refuses)

        assert len(frames) == 0

    def test_a_damaged_file_that_still_decodes_keeps_ffmpegs_complaints_out_of_the_log(self):
        class _DecodedWhileComplaining:
            stdout = bytes(SAMPLE_HEIGHT * SAMPLE_WIDTH)
            stderr = b"corrupt macroblock"

        frames, warning = self._decoded(lambda command, **kwargs: _DecodedWhileComplaining())

        assert len(frames) == 1
        warning.assert_not_called()


class TestWhatItKnows:
    def test_it_takes_paths_and_returns_numbers_reading_no_library_and_writing_no_record(self):
        tree = ast.parse((PROJECT_ROOT / "util" / "frame_hashes.py").read_text(encoding="utf-8"))
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for alias in node.names}
        imported |= {f"{node.module}.{alias.name}" for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) for alias in node.names}

        assert {name for name in imported
                if name.split(".")[0] == "config"
                or name.startswith(("util.sidecar", "util.library_records", "util.media_files"))} == set()


class TestFramesAt:
    def _commands(self, seconds: list[float]) -> list[list[str]]:
        commands: list[list[str]] = []

        class _Finished:
            stdout = bytes(SAMPLE_HEIGHT * SAMPLE_WIDTH)

        with patch.object(fh, "content_crop", lambda video: (1440, 1080, 240, 0)), \
             patch.object(fh.subprocess, "run",
                          lambda command, **kwargs: commands.append(command) or _Finished()):
            frames = fh.frames_at(Path("scene.mp4"), seconds)
        assert frames.shape == (len(seconds), SAMPLE_HEIGHT, SAMPLE_WIDTH)
        return commands

    def test_each_moment_is_one_frame_read_after_seeking_to_it(self):
        commands = self._commands([12.5, 40.0])

        assert [command[command.index("-ss") + 1] for command in commands] == ["12.500", "40.000"]
        for command in commands:
            assert command.index("-ss") < command.index("-i")
            assert command[command.index("-frames:v") + 1] == "1"

    def test_the_bars_come_off_a_moment_as_they_do_a_run_of_frames(self):
        (command,) = self._commands([12.5])

        assert command[command.index("-vf") + 1] == (
            f"crop=1440:1080:240:0,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area"
        )

    def test_a_moment_ffmpeg_cannot_read_is_left_out(self):
        class _Nothing:
            stdout = b""

        with patch.object(fh, "content_crop", lambda video: None), \
             patch.object(fh.subprocess, "run", lambda command, **kwargs: _Nothing()):
            assert len(fh.frames_at(Path("scene.mp4"), [1.0, 2.0])) == 0


class TestAlign:
    def test_bars_stop_a_clip_aligning_with_the_scene_it_came_from(self):
        rng = np.random.default_rng(21)
        scene = rng.integers(40, 220, size=(60, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)
        excerpt = scene[20:50]
        narrow = np.linspace(0, SAMPLE_WIDTH - 1, SAMPLE_WIDTH - 8).round().astype(int)
        pillarboxed = np.zeros_like(excerpt)
        pillarboxed[:, :, 4:-4] = excerpt[:, :, narrow]

        assert align(frame_hashes(excerpt), frame_hashes(scene), fps=8.0) is not None
        assert align(frame_hashes(pillarboxed), frame_hashes(scene), fps=8.0) is None

    def test_finds_where_the_excerpt_sits(self):
        scene = _hashes(400)
        clip = scene[120:160]

        found = align(clip, scene, fps=8.0)

        assert found is not None
        assert found.offset == 15.0

    def test_an_excerpt_whose_hashes_reencoding_nudged_a_few_bits_still_aligns(self):
        scene = _hashes(400)
        clip = scene[120:160] ^ np.uint64(0b1011)

        found = align(clip, scene, fps=8.0)

        assert found is not None
        assert found.offset == 15.0

    def test_a_still_moment_counts_each_clip_frame_once_not_once_per_offset_it_matches(self):
        scene = _hashes(400)
        still = scene[300]
        scene[300:340] = still
        clip = np.concatenate([np.full(10, still, dtype=np.uint64), _hashes(30, seed=5)])

        found = align(clip, scene, fps=8.0)

        assert found is not None
        assert found.score == 10 / 40

    def test_lookalike_frames_scattered_over_a_scene_never_agree_on_one_offset(self):
        clip, scene = _hashes(40, seed=1), _hashes(400, seed=2)
        for clip_frame, scene_frame in ((3, 17), (11, 250), (12, 88), (30, 301), (37, 130)):
            scene[scene_frame] = clip[clip_frame]

        assert align(clip, scene, fps=8.0) is None

    def test_an_excerpt_sampled_off_another_frame_rate_spreads_over_neighbor_offsets_yet_counts_whole(self):
        scene = _hashes(400)
        clip = np.array([scene[200 + i + (i % 2)] for i in range(40)], dtype=np.uint64)

        found = align(clip, scene, fps=8.0)

        assert found is not None
        assert found.score == 1.0
        assert abs(found.offset - 25.0) <= 1 / 8


class TestLocate:
    def test_picks_the_candidate_whose_frames_are_in_the_scene(self):
        scene = _hashes(400)
        candidates = {
            Path("wrong.mp4"): _hashes(40, seed=7),
            Path("right.mp4"): scene[200:240],
            Path("also wrong.mp4"): _hashes(40, seed=8),
        }

        found = locate(scene, candidates, fps=8.0)

        assert found is not None
        assert found.clip == Path("right.mp4")
        assert found.offset == 25.0

    def test_no_candidate_belongs_to_this_scene(self):
        candidates = {Path(f"{i}.mp4"): _hashes(40, seed=10 + i) for i in range(3)}

        assert locate(_hashes(400), candidates, fps=8.0) is None
