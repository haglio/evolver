"""The video asked for now, from the Upscale Queue window: asked for, put first, withdrawn."""
from __future__ import annotations

import time
import unittest

import config
from tasks import nonai_queue, nonai_request, nonai_upscale
from tests.temp_helpers import (
    make_video,
    override_config,
    probes,
    request_of,
    workspace_temp_dir,
    write_job,
)
from tests.temp_helpers import nonai_library_overrides as library_overrides
from util import nonai_job


class TestAskingForOneNow(unittest.TestCase):
    """What the queue window's "upscale this now" does the moment it is asked,
    before any run picks the request up."""

    def test_it_leads_the_queue_and_is_recorded_as_asked_for(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "lagoon" / "0 unsorted" / "b.mp4")

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                nonai_request.request_now("lagoon/0 unsorted/b.mp4")

            assert nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]) == ["lagoon/0 unsorted/b.mp4"]
            assert request_of(overrides) == nonai_job.Request("lagoon/0 unsorted/b.mp4")

    def test_it_stops_the_encode_in_flight_and_queues_that_video_next(self):
        """Stopping here rather than on the next run is what lets that run
        upscale its AI clips first: they wait on any live Topaz process."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _busy, tmp, _out = write_job(root, overrides)
            make_video(overrides["NON_AI_DIR"] / "lagoon" / "0 unsorted" / "b.mp4")

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                nonai_request.request_now("lagoon/0 unsorted/b.mp4")

            mocks["terminate"].assert_called_once_with(4242)
            assert not tmp.exists()
            assert nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"]) is None
            assert nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]) == ["lagoon/0 unsorted/b.mp4", "lagoon/0 unsorted/busy.mp4"]
            assert request_of(overrides).video == "lagoon/0 unsorted/b.mp4"

    def test_asking_for_the_one_already_encoding_lets_it_run_on(self):
        """It is already the video wanted; killing it to start it again would
        throw away the hours it has done."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, suspended=True, suspended_at=time.time() - 60)

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                nonai_request.request_now("lagoon/0 unsorted/busy.mp4")

            mocks["terminate"].assert_not_called()
            mocks["resume"].assert_called_once_with(4242)
            job = nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"])
            assert job["on_request"]
            assert not job["suspended"]
            assert request_of(overrides) is None


class TestPuttingOneFirst(unittest.TestCase):
    """A video dragged to the top of the queue window: it is next, and it waits
    for the usual moment to start like any other."""

    def test_it_leads_the_queue_without_being_asked_for(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "lagoon" / "0 unsorted" / "b.mp4")

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                nonai_request.put_first("lagoon/0 unsorted/b.mp4")

            assert nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]) == ["lagoon/0 unsorted/b.mp4"]
            assert request_of(overrides) is None

    def test_it_takes_over_from_the_encode_in_flight_which_goes_next(self):
        """Put first means first: the encode of another video stops, and that
        video waits second in line to start over."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _busy, tmp, _out = write_job(root, overrides, suspended=True)
            make_video(overrides["NON_AI_DIR"] / "lagoon" / "0 unsorted" / "b.mp4")

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                nonai_request.put_first("lagoon/0 unsorted/b.mp4")

            mocks["terminate"].assert_called_once_with(4242)
            assert not tmp.exists()
            assert nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"]) is None
            assert nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]) == ["lagoon/0 unsorted/b.mp4", "lagoon/0 unsorted/busy.mp4"]
            assert request_of(overrides) is None

    def test_a_video_asked_for_and_not_yet_started_goes_next_and_is_no_longer_asked_for(self):
        """Only the first video can be asked for, and it is no longer first."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            for name in "ab":
                make_video(overrides["NON_AI_DIR"] / "lagoon" / "0 unsorted" / f"{name}.mp4")

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                nonai_request.request_now("lagoon/0 unsorted/a.mp4")
                nonai_request.put_first("lagoon/0 unsorted/b.mp4")

            assert nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]) == ["lagoon/0 unsorted/b.mp4", "lagoon/0 unsorted/a.mp4"]
            assert request_of(overrides) is None


class TestWithdrawingTheAsk(unittest.TestCase):
    """The queue window's hollow arrow: the first video stays first, and goes
    back to waiting for nobody to be at the computer."""

    def test_a_video_not_yet_started_is_no_longer_asked_for_and_keeps_its_place(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "lagoon" / "0 unsorted" / "b.mp4")

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                nonai_request.request_now("lagoon/0 unsorted/b.mp4")
                nonai_request.withdraw_request()

            assert request_of(overrides) is None
            assert nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]) == ["lagoon/0 unsorted/b.mp4"]

    def test_an_encode_already_running_is_parked_again_while_you_are_here(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, tmp, _out = write_job(root, overrides, on_request=True)

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG),
                                  idle_seconds=5.0)
            with override_config(**overrides), stack:
                nonai_request.withdraw_request()
                changed = nonai_upscale.throttle_to_presence()

            assert changed == "suspended"
            mocks["suspend"].assert_called_once_with(4242)
            mocks["terminate"].assert_not_called()
            assert tmp.exists()
            assert "on_request" not in nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"])
