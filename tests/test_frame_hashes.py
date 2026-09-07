"""Reading two videos down to comparable frames, and finding one inside the other."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from util import frame_hashes as fh
from util.frame_hashes import (
    MIN_PICTURE_FRACTION,
    SAMPLE_HEIGHT,
    SAMPLE_WIDTH,
    align,
    frame_hashes,
    locate,
    picture_crop,
)


def _hashes(n: int, seed: int = 0) -> np.ndarray:
    """A run of *n* distinct frame hashes, as an unrelated video would give."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2**64, size=n, dtype=np.uint64)


class TestFrameHashes:
    def test_a_dimmer_copy_of_a_frame_hashes_the_same(self):
        """The clip and the scene are different encodes of one picture, so what
        the hash reads has to be the shape of the frame, not its exposure."""
        rng = np.random.default_rng(3)
        frames = rng.integers(40, 200, size=(5, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)

        assert list(frame_hashes(frames - 20)) == list(frame_hashes(frames))

    def test_a_video_ffmpeg_could_not_read_hashes_to_nothing(self):
        """One unreadable file among hundreds must cost that file its match, not
        the whole batch."""
        nothing = np.empty((0, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)

        assert len(frame_hashes(nothing)) == 0
        assert align(frame_hashes(nothing), _hashes(400), fps=8.0) is None

    def test_different_frames_hash_differently(self):
        rng = np.random.default_rng(4)
        frames = rng.integers(0, 256, size=(20, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)

        assert len(set(frame_hashes(frames).tolist())) == 20


class TestPictureCrop:
    """What to crop off a frame, read out of ffmpeg's cropdetect reports."""

    def _report(self, width: int, height: int, x: int = 0, y: int = 0) -> str:
        return (
            f"[Parsed_cropdetect_0 @ 000] x1:{x} x2:0 y1:{y} y2:0 w:{width} h:{height} "
            f"x:{x} y:{y} pts:1 t:0.04 limit:24 crop={width}:{height}:{x}:{y}"
        )

    def test_finds_the_picture_inside_a_pillarboxed_frame(self):
        report = self._report(1440, 1080, x=240)

        assert picture_crop([report], 1920, 1080) == (1440, 1080, 240, 0)

    def test_a_frame_with_no_bars_is_left_alone(self):
        report = self._report(1920, 1080)

        assert picture_crop([report], 1920, 1080) is None

    def test_the_widest_window_wins(self):
        """A window that lands on a fade or a dark shot reads black where there
        is picture. Cropping a scene its own clip does not crop is how a real
        pair stops matching, so a narrow reading never overrides a wide one."""
        dark = self._report(600, 400, x=660, y=340)
        lit = self._report(1440, 1080, x=240)

        assert picture_crop([dark, lit, dark], 1920, 1080) == (1440, 1080, 240, 0)

    def test_a_video_that_reads_as_nearly_all_black_is_left_alone(self):
        """Below this much picture the likelier story is a dark video, not a
        letterbox -- no real one takes half the frame."""
        sliver = int(1080 * MIN_PICTURE_FRACTION) - 20
        report = self._report(1920, sliver, y=(1080 - sliver) // 2)

        assert picture_crop([report], 1920, 1080) is None

    def test_nothing_measured_means_nothing_cropped(self):
        assert picture_crop(["ffmpeg version 7.1", ""], 1920, 1080) is None

    def test_the_rectangle_is_even_on_every_side(self):
        """Chroma is subsampled, so ffmpeg's crop refuses an odd rectangle."""
        crop = picture_crop([self._report(1437, 1077, x=241, y=1)], 1920, 1080)

        assert crop is not None
        assert not any(value % 2 for value in crop)


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
        """The filter chain ``sample_frames`` builds for a video cropped *crop*."""
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
        """Scaling first would squash the bars into the thumbnail, which is the
        whole problem -- the picture has to fill the grid the hash reads."""
        assert self._filters((1440, 1080, 240, 0)) == (
            f"fps=8.0,crop=1440:1080:240:0,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area"
        )

    def test_a_video_with_no_bars_is_scaled_whole(self):
        assert self._filters(None) == (
            f"fps=8.0,scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT}:flags=area"
        )


class TestAlign:
    def test_bars_stop_a_clip_aligning_with_the_scene_it_came_from(self):
        """Why the crop happens at all. A hash says where things sit in the
        frame, so pillarboxing a scene into a wider one moves its whole picture
        inward and hashes as a different video -- a real excerpt then places
        none of itself, which is what a 4:3 scene cut into a 16:9 compilation
        did."""
        rng = np.random.default_rng(21)
        scene = rng.integers(40, 220, size=(60, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)
        excerpt = scene[20:50]
        # The same pixels, squeezed into the middle of a frame of black.
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

    def test_a_clip_from_elsewhere_does_not_align(self):
        """Frames of unrelated videos collide often enough at this tolerance --
        two performers on one bed look alike pooled down to 72 cells. What
        scattered collisions cannot do is agree on a single offset."""
        clip, scene = _hashes(40, seed=1), _hashes(400, seed=2)
        for clip_frame, scene_frame in ((3, 17), (11, 250), (12, 88), (30, 301), (37, 130)):
            scene[scene_frame] = clip[clip_frame]

        assert align(clip, scene, fps=8.0) is None

    def test_counts_an_excerpt_that_jitters_by_a_frame(self):
        """Sampling 8 a second off a 24fps scene lands on exact source frames; off
        a 30fps clip it does not, so consecutive frames of one excerpt answer to
        offsets a bucket apart. Scoring only the single best bucket read a real
        match -- a 4:3 scene against its 16:9 clip -- as 31% of itself."""
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
        """Most of the library's scenes were never in a compilation; a performer
        with several scenes still offers their other clips as candidates, and
        every one of them has to be turned down."""
        candidates = {Path(f"{i}.mp4"): _hashes(40, seed=10 + i) for i in range(3)}

        assert locate(_hashes(400), candidates, fps=8.0) is None
