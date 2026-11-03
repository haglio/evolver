from __future__ import annotations

from pathlib import Path

import numpy as np

from util import same_footage
from util.frame_hashes import SAMPLE_HEIGHT, SAMPLE_WIDTH, frame_hashes

MASK = (1 << 64) - 1
MOMENTS = [(0x9E3779B97F4A7C15 * (moment + 1)) & MASK for moment in range(16)]


def _written(values: list[int]) -> list[str]:
    return [f"{value:016x}" for value in values]


def _reencoded(agreeing: int) -> list[int]:
    return [value ^ 0b1011 if moment < agreeing else value ^ MASK
            for moment, value in enumerate(MOMENTS)]


class TestSameFootage:
    def test_another_encode_agreeing_at_most_moments_is_the_same_footage(self):
        assert same_footage.same_footage(_written(MOMENTS), _written(_reencoded(10)))

    def test_agreeing_at_only_some_moments_is_other_footage(self):
        assert not same_footage.same_footage(_written(MOMENTS), _written(_reencoded(9)))


def _frames(count: int) -> np.ndarray:
    rng = np.random.default_rng(count)
    return rng.integers(0, 256, size=(count, SAMPLE_HEIGHT, SAMPLE_WIDTH), dtype=np.uint8)


class TestFingerprint:
    def test_the_moments_are_spread_evenly_through_the_running_time(self):
        asked: list[float] = []

        def grab(video: Path, seconds: list[float]) -> np.ndarray:
            asked.extend(seconds)
            return _frames(len(seconds))

        same_footage.fingerprint(Path("scene.mp4"), 160.0, grab=grab)

        assert asked == [5.0 + 10.0 * moment for moment in range(16)]

    def test_each_moment_is_written_as_its_frame_hash(self):
        frames = _frames(16)

        written = same_footage.fingerprint(Path("scene.mp4"), 160.0, grab=lambda video, seconds: frames)

        assert written == [f"{value:016x}" for value in frame_hashes(frames).tolist()]

    def test_a_video_whose_moments_cannot_all_be_read_has_none(self):
        assert same_footage.fingerprint(
            Path("scene.mp4"), 160.0, grab=lambda video, seconds: _frames(11)) is None


class TestJoin:
    def test_a_pair_folds_two_families_into_the_one_whose_id_sorts_first(self):
        ids = {"scene one": "scene one", "copy": "copy", "other": "other"}

        assert same_footage.join(ids, [("scene one", "copy")]) == {
            "scene one": "copy", "copy": "copy", "other": "other"}

    def test_pairs_that_chain_end_in_one_family(self):
        ids = {"a": "a", "b": "b", "c": "c"}

        assert same_footage.join(ids, [("c", "b"), ("b", "a")]) == {"a": "a", "b": "a", "c": "a"}

    def test_no_pairs_leaves_every_family_as_it_was(self):
        assert same_footage.join({"a": "a", "b": "b"}, []) == {"a": "a", "b": "b"}


class TestFingerprinted:
    def test_records_the_moments_and_keeps_the_rest_without_touching_the_original(self):
        payload = {"title": "scene one", same_footage.BLOCK: {"other": 1}}

        recorded = same_footage.fingerprinted(payload, ["00"] * 16)

        assert recorded == {"title": "scene one", same_footage.BLOCK: {"other": 1, same_footage.FIELD: ["00"] * 16}}
        assert payload == {"title": "scene one", same_footage.BLOCK: {"other": 1}}

    def test_a_record_with_no_block_gets_one(self):
        assert same_footage.fingerprinted({}, ["00"] * 16) == {same_footage.BLOCK: {same_footage.FIELD: ["00"] * 16}}

