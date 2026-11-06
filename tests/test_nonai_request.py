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
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, suspended=True, suspended_at=time.time() - 60)

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                nonai_request.request_now("lagoon/0 unsorted/busy.mp4")

            mocks["terminate"].assert_not_called()
            mocks["resume"].assert_called_once_with(4242)
            job = nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"])
            assert job.on_request
            assert not job.suspended
            assert request_of(overrides) is None


class TestPuttingOneFirst(unittest.TestCase):
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
            assert "on_request" not in nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"]).fields()


class TestAnEncodeThatHasAlreadyEnded:
    def test_asking_for_another_video_leaves_it_alone_to_be_concluded(self):
        job = nonai_job.Job({"pid": None, "source": "lagoon/0 unsorted/a.mp4"})

        assert nonai_request.make_way_for("lagoon/0 unsorted/b.mp4", job, files=None) == (job, "")
