from __future__ import annotations

import json
import subprocess
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import config
from tasks import nonai_encode, nonai_queue, nonai_upscale
from tests.temp_helpers import (
    STARTED_UNDER,
    make_video,
    override_config,
    workspace_temp_dir,
    write_job,
    write_sidecar,
)
from tests.temp_helpers import (
    nonai_library_overrides as library_overrides,
)
from util import nonai_job, provenance, sidecar, video_type
from util.media_files import partial_path


def probes(videoai="", orientation="landscape", duration=100.0, free_bytes=10**15,
           popen=None, is_running=True, image="ffmpeg.exe", terminate=True,
           topaz_pids=(), cmdline=None, available_ram=64.0, idle_seconds=10_000.0):
    """An ExitStack patching every outside contact the stage makes.

    Patched on the module that owns each function rather than through whichever
    stage module imports it: ``patch("tasks.nonai_upscale.processes.suspend")``
    resolves ``processes`` to ``util.processes`` and sets the attribute there
    anyway, so the prefix never scoped anything -- it only recorded which file
    happened to call it, and went stale the moment the call moved.

    idle_seconds defaults to a long idle (the user is away), so the presence
    throttle lets encodes start unless a test says otherwise.
    """
    stack = ExitStack()
    mocks = {
        "idle_seconds": stack.enter_context(
            patch("util.system_resources.seconds_since_last_input",
                  return_value=idle_seconds)),
        "suspend": stack.enter_context(
            patch("util.processes.suspend", return_value=True)),
        "resume": stack.enter_context(
            patch("util.processes.resume", return_value=True)),
        "videoai": stack.enter_context(
            patch("util.ffprobe.videoai_tag", return_value=videoai)),
        "orientation": stack.enter_context(
            patch("util.ffprobe.orientation_of", return_value=orientation)),
        "duration": stack.enter_context(
            patch("util.ffprobe.duration_seconds", return_value=duration)),
        "free_bytes": stack.enter_context(
            patch("util.system_resources.free_bytes", return_value=free_bytes)),
        "available_ram": stack.enter_context(
            patch("util.system_resources.available_ram_gb", return_value=available_ram)),
        "popen": stack.enter_context(
            patch("subprocess.Popen", popen or Mock(return_value=Mock(pid=4242)))),
        "is_running": stack.enter_context(
            patch("util.processes.is_running", return_value=is_running)),
        "image_path": stack.enter_context(
            patch("util.processes.image_path", return_value=image)),
        "terminate": stack.enter_context(
            patch("util.processes.terminate", return_value=terminate)),
        "pids_of_image": stack.enter_context(
            patch("util.processes.pids_of_image", return_value=list(topaz_pids))),
        "command_line": stack.enter_context(
            patch("util.processes.command_line", return_value=cmdline)),
        "sign_in_expired": stack.enter_context(
            patch("util.topaz.sign_in_expired", return_value=False)),
    }
    return stack, mocks


class TestRunStartsAJob(unittest.TestCase):
    def test_launches_detached_ffmpeg_for_the_top_candidate(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            video = make_video(non_ai / "larkin" / "0 unsorted" / "a.mp4")

            stack, mocks = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "larkin/0 unsorted/a.mp4")
            cmd = mocks["popen"].call_args.args[0]
            self.assertIn(str(video), cmd)
            self.assertNotIn("-an", cmd)
            self.assertIn("aac", cmd)
            filter_arg = cmd[cmd.index("-filter_complex") + 1]
            self.assertIn("w=3840:h=2160", filter_arg)
            self.assertIn("iris-2", filter_arg)

            job = json.loads(overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertEqual(job["pid"], 4242)
            self.assertEqual(job["source"], str(video))
            self.assertEqual(job["expected_duration"], 100.0)

    def test_the_file_an_encode_writes_until_promotion_carries_no_video_extension(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            stack, mocks = probes()
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=True)

            job = json.loads(overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertEqual(mocks["popen"].call_args.args[0][-1], job["tmp"])
            self.assertFalse(job["tmp"].lower().endswith(tuple(config.VIDEO_EXTENSIONS)))

    def test_an_already_tagged_candidate_is_skipped_and_the_next_one_starts(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "larkin" / "0 unsorted" / "a tagged.mp4")
            fresh = make_video(non_ai / "larkin" / "0 unsorted" / "b fresh.mp4")

            stack, mocks = probes()
            mocks["videoai"].side_effect = ["Enhanced using iris-2", ""]
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "larkin/0 unsorted/b fresh.mp4")
            self.assertIn(str(fresh), mocks["popen"].call_args.args[0])
            skip_list = overrides["NONAI_SKIP_LIST"].read_text(encoding="utf-8")
            self.assertIn("larkin/0 unsorted/a tagged.mp4\t", skip_list)

    def test_allow_start_false_starts_nothing(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            stack, mocks = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.started, "")
            self.assertEqual(result.pending, 1)
            mocks["popen"].assert_not_called()

    def test_low_disk_defers_the_start(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            stack, mocks = probes(free_bytes=1)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertTrue(result.deferred_low_disk)
            self.assertEqual(result.started, "")
            mocks["popen"].assert_not_called()


class TestStartGuards(unittest.TestCase):
    """A new multi-hour encode only starts on a machine with headroom."""

    def _one_candidate(self, overrides):
        return make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

    def test_a_running_topaz_process_defers_the_start(self):
        """Any live Topaz ffmpeg — an orphaned encode, or the user's own GUI
        export — means the GPU is taken; starting a second would stack encodes."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            self._one_candidate(overrides)

            stack, mocks = probes(topaz_pids=(31337,))
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "")
            self.assertEqual(result.start_deferred, "topaz_busy")
            mocks["popen"].assert_not_called()

    def test_low_available_ram_defers_the_start(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            self._one_candidate(overrides)

            stack, mocks = probes(available_ram=2.5)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "")
            self.assertEqual(result.start_deferred, "low_ram")
            mocks["popen"].assert_not_called()

    def test_a_present_user_defers_the_start(self):
        """Recent keyboard/mouse input means the user is at the machine; a
        multi-hour encode waits until they step away."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            self._one_candidate(overrides)

            stack, mocks = probes(idle_seconds=5.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "")
            self.assertEqual(result.start_deferred, "user_present")
            mocks["popen"].assert_not_called()

    def test_an_expired_topaz_sign_in_defers_the_start(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            self._one_candidate(overrides)

            stack, mocks = probes()
            mocks["sign_in_expired"].return_value = True
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "")
            self.assertEqual(result.start_deferred, "topaz_sign_in_expired")
            mocks["popen"].assert_not_called()

    def test_the_sign_in_is_only_checked_when_nothing_else_holds_the_start(self):
        for held in (dict(topaz_pids=(31337,)), dict(idle_seconds=5.0)):
            with self.subTest(held=sorted(held)), workspace_temp_dir() as root:
                overrides = library_overrides(root)
                self._one_candidate(overrides)

                stack, mocks = probes(**held)
                with override_config(**overrides), stack:
                    nonai_upscale.run(allow_start=True)

                mocks["sign_in_expired"].assert_not_called()

    def test_an_idled_out_user_allows_the_start(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            self._one_candidate(overrides)

            stack, _mocks = probes(
                idle_seconds=nonai_encode.EncodeSettings().user_idle_threshold_seconds + 60)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "larkin/0 unsorted/a.mp4")
            self.assertEqual(result.start_deferred, "")

    def test_a_recent_encode_imposes_a_cooldown(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            self._one_candidate(overrides)
            overrides["NONAI_COOLDOWN_FILE"].write_text(
                json.dumps({"ended_at": time.time() - 60}), encoding="utf-8"
            )

            stack, mocks = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "")
            self.assertEqual(result.start_deferred, "cooldown")
            mocks["popen"].assert_not_called()

    def test_an_old_cooldown_stamp_does_not_block(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            self._one_candidate(overrides)
            overrides["NONAI_COOLDOWN_FILE"].write_text(
                json.dumps({"ended_at": time.time() - nonai_encode.EncodeSettings().cooldown_minutes * 60 - 60}),
                encoding="utf-8",
            )

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "larkin/0 unsorted/a.mp4")
            self.assertEqual(result.start_deferred, "")


def ask_for(overrides, video):
    nonai_job.save_request(overrides["NONAI_REQUEST_FILE"], nonai_job.Request(video))


def request_of(overrides):
    return nonai_job.load_request(overrides["NONAI_REQUEST_FILE"])


class TestRunStartsWhatYouAskedFor(unittest.TestCase):
    """A video asked for from the queue window starts on the next run, even
    while the user is at the computer -- that is what asking for it now means."""

    def test_the_video_you_asked_for_starts_while_you_are_at_the_computer(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")
            ask_for(overrides, "larkin/0 unsorted/b.mp4")

            stack, mocks = probes(idle_seconds=5.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, take_requests=True)

            self.assertEqual(result.started, "larkin/0 unsorted/b.mp4")
            self.assertTrue(result.on_request)
            mocks["popen"].assert_called_once()
            self.assertIsNone(request_of(overrides))

    def test_an_encode_of_another_video_is_stopped_to_make_way(self):
        """The window stops it when the video is dropped; a run stops it too,
        for the encode that was adopted or started after the ask."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _busy, tmp, _out = write_job(root, overrides)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")
            ask_for(overrides, "larkin/0 unsorted/b.mp4")

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, take_requests=True)

            mocks["terminate"].assert_called_once_with(4242)
            self.assertFalse(tmp.exists())
            self.assertEqual(result.stopped, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.started, "larkin/0 unsorted/b.mp4")
            self.assertTrue(result.on_request)

    def test_a_machine_short_of_memory_holds_it_back_and_says_so(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")
            ask_for(overrides, "larkin/0 unsorted/b.mp4")

            stack, mocks = probes(available_ram=2.5)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, take_requests=True)

            self.assertEqual((result.started, result.start_deferred), ("", "low_ram"))
            mocks["popen"].assert_not_called()
            self.assertEqual(request_of(overrides),
                             nonai_job.Request("larkin/0 unsorted/b.mp4", held_back="low_ram"))

    def test_the_breather_after_the_last_encode_does_not_hold_it_back(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")
            ask_for(overrides, "larkin/0 unsorted/b.mp4")
            nonai_job.stamp_encode_ended(overrides["NONAI_COOLDOWN_FILE"])

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, take_requests=True)

            self.assertEqual(result.started, "larkin/0 unsorted/b.mp4")

    def test_a_nearly_full_drive_holds_it_back_and_says_so(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")
            ask_for(overrides, "larkin/0 unsorted/b.mp4")

            stack, mocks = probes(free_bytes=10)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, take_requests=True)

            self.assertEqual(result.started, "")
            self.assertTrue(result.deferred_low_disk)
            mocks["popen"].assert_not_called()
            self.assertEqual(request_of(overrides).held_back, "low_disk")

    def test_a_video_that_has_left_the_queue_stops_being_waited_for(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")
            ask_for(overrides, "larkin/0 unsorted/gone.mp4")

            stack, mocks = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, take_requests=True)

            self.assertEqual(result.started, "")
            mocks["popen"].assert_not_called()
            self.assertIsNone(request_of(overrides))

    def test_new_ai_clips_still_waiting_go_first(self):
        """An AI clip takes a minute and an asked-for encode takes hours, and
        once it runs no AI clip can until it ends."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")
            ask_for(overrides, "larkin/0 unsorted/b.mp4")

            stack, mocks = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, take_requests=True,
                                           ai_waiting=True)

            self.assertEqual((result.started, result.start_deferred),
                             ("", "ai_clips_waiting"))
            mocks["popen"].assert_not_called()
            self.assertEqual(request_of(overrides).held_back, "ai_clips_waiting")


class TestAskingForOneNow(unittest.TestCase):
    """What the queue window's "upscale this now" does the moment it is asked,
    before any run picks the request up."""

    def test_it_leads_the_queue_and_is_recorded_as_asked_for(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                nonai_upscale.request_now("larkin/0 unsorted/b.mp4")

            self.assertEqual(nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]),
                             ["larkin/0 unsorted/b.mp4"])
            self.assertEqual(request_of(overrides), nonai_job.Request("larkin/0 unsorted/b.mp4"))

    def test_it_stops_the_encode_in_flight_and_queues_that_video_next(self):
        """Stopping here rather than on the next run is what lets that run
        upscale its AI clips first: they wait on any live Topaz process."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _busy, tmp, _out = write_job(root, overrides)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                nonai_upscale.request_now("larkin/0 unsorted/b.mp4")

            mocks["terminate"].assert_called_once_with(4242)
            self.assertFalse(tmp.exists())
            self.assertIsNone(nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"]))
            self.assertEqual(nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]),
                             ["larkin/0 unsorted/b.mp4", "larkin/0 unsorted/busy.mp4"])
            self.assertEqual(request_of(overrides).video, "larkin/0 unsorted/b.mp4")

    def test_asking_for_the_one_already_encoding_lets_it_run_on(self):
        """It is already the video wanted; killing it to start it again would
        throw away the hours it has done."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, suspended=True, suspended_at=time.time() - 60)

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                nonai_upscale.request_now("larkin/0 unsorted/busy.mp4")

            mocks["terminate"].assert_not_called()
            mocks["resume"].assert_called_once_with(4242)
            job = nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"])
            self.assertTrue(job["on_request"])
            self.assertFalse(job["suspended"])
            self.assertIsNone(request_of(overrides))


class TestPuttingOneFirst(unittest.TestCase):
    """A video dragged to the top of the queue window: it is next, and it waits
    for the usual moment to start like any other."""

    def test_it_leads_the_queue_without_being_asked_for(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                nonai_upscale.put_first("larkin/0 unsorted/b.mp4")

            self.assertEqual(nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]),
                             ["larkin/0 unsorted/b.mp4"])
            self.assertIsNone(request_of(overrides))

    def test_it_takes_over_from_the_encode_in_flight_which_goes_next(self):
        """Put first means first: the encode of another video stops, and that
        video waits second in line to start over."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _busy, tmp, _out = write_job(root, overrides, suspended=True)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                nonai_upscale.put_first("larkin/0 unsorted/b.mp4")

            mocks["terminate"].assert_called_once_with(4242)
            self.assertFalse(tmp.exists())
            self.assertIsNone(nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"]))
            self.assertEqual(nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]),
                             ["larkin/0 unsorted/b.mp4", "larkin/0 unsorted/busy.mp4"])
            self.assertIsNone(request_of(overrides))

    def test_a_video_asked_for_and_not_yet_started_goes_next_and_is_no_longer_asked_for(self):
        """Only the first video can be asked for, and it is no longer first."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            for name in "ab":
                make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / f"{name}.mp4")

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                nonai_upscale.request_now("larkin/0 unsorted/a.mp4")
                nonai_upscale.put_first("larkin/0 unsorted/b.mp4")

            self.assertEqual(nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]),
                             ["larkin/0 unsorted/b.mp4", "larkin/0 unsorted/a.mp4"])
            self.assertIsNone(request_of(overrides))


class TestWithdrawingTheAsk(unittest.TestCase):
    """The queue window's hollow arrow: the first video stays first, and goes
    back to waiting for nobody to be at the computer."""

    def test_a_video_not_yet_started_is_no_longer_asked_for_and_keeps_its_place(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "b.mp4")

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                nonai_upscale.request_now("larkin/0 unsorted/b.mp4")
                nonai_upscale.withdraw_request()

            self.assertIsNone(request_of(overrides))
            self.assertEqual(nonai_queue.listed_videos(overrides["NONAI_PIN_LIST"]),
                             ["larkin/0 unsorted/b.mp4"])

    def test_an_encode_already_running_is_parked_again_while_you_are_here(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, tmp, _out = write_job(root, overrides, on_request=True)

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG),
                                  idle_seconds=5.0)
            with override_config(**overrides), stack:
                nonai_upscale.withdraw_request()
                changed = nonai_upscale.throttle_to_presence()

            self.assertEqual(changed, "suspended")
            mocks["suspend"].assert_called_once_with(4242)
            mocks["terminate"].assert_not_called()
            self.assertTrue(tmp.exists())
            self.assertNotIn("on_request", nonai_job.load_job(overrides["NONAI_JOB_STATE_FILE"]))


class TestAnEncodeYouAskedForRunsOn(unittest.TestCase):
    """Presence parks the encodes Evolver picked for itself. The one the user
    asked for is the exception: it was wanted while they were at the computer."""

    def test_a_present_user_does_not_park_it(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, on_request=True)

            stack, mocks = probes(is_running=True, idle_seconds=5.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, presence_managed=True)

            self.assertEqual(result.in_flight, "larkin/0 unsorted/busy.mp4")
            self.assertFalse(result.suspended)
            self.assertTrue(result.on_request)
            mocks["suspend"].assert_not_called()

    def test_the_fast_presence_poll_leaves_it_alone_too(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, on_request=True)

            stack, mocks = probes(is_running=True, idle_seconds=5.0)
            with override_config(**overrides), stack:
                changed = nonai_upscale.throttle_to_presence()

            self.assertEqual(changed, "")
            mocks["suspend"].assert_not_called()

    def test_the_idle_time_toggle_being_off_does_not_kill_it(self):
        """Off means Evolver picks nothing of its own; it does not take back a
        video the user asked for while it was off."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, tmp, _out = write_job(root, overrides, on_request=True)

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, stop=True)

            self.assertEqual(result.in_flight, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.stopped, "")
            mocks["terminate"].assert_not_called()
            self.assertTrue(tmp.exists())


class TestRunStopsAJob(unittest.TestCase):
    def test_stop_kills_the_running_encode_without_penalizing_the_video(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, tmp, out = write_job(root, overrides)
            overrides["NONAI_ATTEMPTS_FILE"].write_text(
                json.dumps({"larkin/0 unsorted/busy.mp4": 1}), encoding="utf-8"
            )
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "next.mp4")

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True, stop=True)

            mocks["terminate"].assert_called_once_with(4242)
            mocks["popen"].assert_not_called()
            self.assertEqual(result.stopped, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.failed, "")
            self.assertEqual(result.started, "")
            self.assertFalse(tmp.exists())
            self.assertFalse(out.exists())
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())
            attempts = json.loads(overrides["NONAI_ATTEMPTS_FILE"].read_text(encoding="utf-8"))
            self.assertNotIn("larkin/0 unsorted/busy.mp4", attempts)
            self.assertFalse(overrides["NONAI_SKIP_LIST"].exists())

    def test_stop_still_promotes_an_encode_that_already_finished(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, _tmp, out = write_job(root, overrides, expected=100.0)

            stack, mocks = probes(is_running=False, duration=100.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, stop=True)

            mocks["terminate"].assert_not_called()
            self.assertEqual(result.promoted, "larkin/0 unsorted/busy.mp4")
            self.assertTrue(out.exists())


# The on-disk record's key names, held exactly. The file lives at
# %LOCALAPPDATA%\Evolver\nonai_upscale_job.json and describes an encode that
# is still running: a renamed key orphans it mid-run, and the stage then sees
# no job, leaves the ffmpeg unsupervised and starts another on top of it --
# which is the failure the adoption path below exists to recover from.
JOB_KEYS_AT_START = {"pid", "source", "tmp", "out", "expected_duration", "started_at",
                     "provenance"}
# Adoption knows three more, because it takes over an encode already in flight
# and must be able to say it is not frozen.
JOB_KEYS_ON_ADOPTION = JOB_KEYS_AT_START | {
    "suspended", "suspended_at", "suspended_seconds",
}


class TestTheJobFilesKeys(unittest.TestCase):
    def test_a_started_encode_writes_exactly_these_keys(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            stack, _ = probes()
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=True)

            written = json.loads(
                overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertEqual(set(written), JOB_KEYS_AT_START)

    def test_an_encode_started_on_request_adds_only_the_mark_that_says_so(self):
        """The mark is what keeps presence and the toggle off it, on every run
        and every presence poll until it ends."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")
            ask_for(overrides, "larkin/0 unsorted/a.mp4")

            stack, _ = probes()
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=False, take_requests=True)

            written = json.loads(
                overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertEqual(set(written), JOB_KEYS_AT_START | {"on_request"})
            self.assertIs(written["on_request"], True)

    def test_an_adopted_encode_writes_exactly_these(self):
        from util import orientation, topaz
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "0 unsorted" / "busy.mp4")
            tmp = (non_ai / "larkin" / "3_good_to_go" / "processed"
                   / "busy.partial.deadbeefcafe.mp4")
            make_video(tmp)
            cmdline = subprocess.list2cmdline(topaz.command(
                source, tmp, topaz.framed(topaz.NON_AI_UPSCALE, orientation.LANDSCAPE)))

            stack, _ = probes(topaz_pids=(31337,), cmdline=cmdline, duration=581.0)
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=False)

            written = json.loads(
                overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertEqual(set(written), JOB_KEYS_ON_ADOPTION)

    def test_suspending_and_resuming_add_no_keys_of_their_own(self):
        """The throttle rewrites the record on every park and thaw, and it is
        the same record: three of the nine exist for exactly this."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides)

            stack, _ = probes(is_running=True, idle_seconds=5.0)
            with override_config(**overrides), stack:
                nonai_upscale.throttle_to_presence()

            written = json.loads(
                overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertEqual(set(written), JOB_KEYS_ON_ADOPTION)


class TestWhatMadeTheUpscale(unittest.TestCase):
    def test_a_started_encode_keeps_the_stamp_of_the_recipe_and_code_that_started_it(self):
        """An encode runs for hours and concludes on a later tick -- sometimes
        after a restart onto newer code -- so what made it is taken when it
        starts, not when it is promoted."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            stack, _ = probes()
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=True)

            stamp = json.loads(
                overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))["provenance"]
            self.assertEqual((stamp["app"], stamp["recipe"], stamp["recipe_version"]),
                             ("evolver", "non_ai_upscale", "v001"))

    def test_a_promoted_upscale_files_the_stamp_its_encode_started_under(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, _tmp, out = write_job(root, overrides, expected=100.0)

            stack, _ = probes(is_running=False, duration=100.0)
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=False)

                stamps = sidecar.read(sidecar.sidecar_path(out)).get(provenance.BLOCK)
            self.assertEqual(stamps, {provenance.UPSCALE_NON_AI: STARTED_UNDER})

    def test_an_encode_started_before_stamps_were_kept_files_one_that_says_so(self):
        """The encode in flight on the day this lands has a record with no stamp
        in it: it was ours, on our recipe, and nothing more is known."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, _tmp, out = write_job(root, overrides, expected=100.0, stamp=None)

            stack, _ = probes(is_running=False, duration=100.0)
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=False)

                stamps = sidecar.read(sidecar.sidecar_path(out)).get(provenance.BLOCK)
            self.assertEqual(stamps, {provenance.UPSCALE_NON_AI: provenance.reconstructed(
                "evolver", recipe="non_ai_upscale")})


class TestOrphanAdoption(unittest.TestCase):
    """A lost job file must not orphan a live encode.

    The file sync service covering the project tree renamed the in-flight job
    file to '... [conflicted N].json' mid-run; the stage then saw no job, the
    running ffmpeg went unsupervised, and fresh starts stacked encodes until
    the machine crashed. With the state file gone, a lone Topaz process is
    re-identified from its own command line and adopted back under supervision.
    """

    def test_a_lone_topaz_process_is_adopted_back_into_a_job(self):
        from util import orientation, topaz
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "0 unsorted" / "busy.mp4")
            processed = non_ai / "larkin" / "3_good_to_go" / "processed"
            tmp = processed / "busy.partial.deadbeefcafe.mp4"
            make_video(tmp)
            cmdline = subprocess.list2cmdline(topaz.command(
                source, tmp, topaz.framed(topaz.NON_AI_UPSCALE, orientation.LANDSCAPE)))

            stack, mocks = probes(topaz_pids=(31337,), cmdline=cmdline, duration=581.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.in_flight, "larkin/0 unsorted/busy.mp4")
            mocks["popen"].assert_not_called()
            job = json.loads(overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertEqual(job["pid"], 31337)
            self.assertEqual(job["source"], str(source))
            self.assertEqual(job["tmp"], str(tmp))
            self.assertEqual(job["out"], str(processed / "busy_apo8_iris2.mp4"))

    def test_multiple_topaz_processes_are_not_adopted(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            stack, mocks = probes(topaz_pids=(111, 222))
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())
            self.assertEqual(result.start_deferred, "topaz_busy")
            mocks["popen"].assert_not_called()

    def test_a_foreign_topaz_process_blocks_starts_but_is_not_adopted(self):
        """The user's own Topaz GUI export writes outside the library."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            stack, mocks = probes(
                topaz_pids=(31337,),
                cmdline=r'"C:\Program Files\Topaz Labs LLC\Topaz Video\ffmpeg.exe" -i "D:\gui\in.mp4" "D:\gui\out.mp4"',
            )
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())
            self.assertEqual(result.start_deferred, "topaz_busy")
            mocks["popen"].assert_not_called()


class TestPresenceThrottle(unittest.TestCase):
    """With the toggle on (presence_managed), the in-flight encode follows the
    user: frozen the moment they return, thawed once they idle out again."""

    def test_a_present_user_suspends_the_in_flight_encode(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, tmp, _ = write_job(root, overrides)

            stack, mocks = probes(is_running=True, idle_seconds=5.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True, presence_managed=True)

            mocks["suspend"].assert_called_once_with(4242)
            mocks["terminate"].assert_not_called()
            self.assertEqual(result.in_flight, "larkin/0 unsorted/busy.mp4")
            self.assertTrue(result.suspended)
            self.assertTrue(tmp.exists())
            job = json.loads(overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertTrue(job["suspended"])

    def test_an_already_suspended_encode_is_not_suspended_again(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, suspended=True, suspended_at=time.time() - 30)

            stack, mocks = probes(is_running=True, idle_seconds=5.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True, presence_managed=True)

            mocks["suspend"].assert_not_called()
            self.assertTrue(result.suspended)

    def test_an_idle_user_resumes_a_suspended_encode(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, suspended=True, suspended_at=time.time() - 120,
                      suspended_seconds=60.0)

            stack, mocks = probes(is_running=True, idle_seconds=10_000.0, duration=None)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True, presence_managed=True)

            mocks["resume"].assert_called_once_with(4242)
            self.assertFalse(result.suspended)
            job = json.loads(overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertFalse(job["suspended"])
            # The completed suspension is banked (60s prior + ~120s open interval).
            self.assertGreater(job["suspended_seconds"], 170.0)

    def test_suspended_time_is_not_charged_against_the_runtime_cap(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            # Wall-clock past the cap, but most of it spent frozen.
            write_job(
                root, overrides,
                started_seconds_ago=nonai_encode.EncodeSettings().max_runtime_hours * 3600 + 3600,
                suspended_seconds=2 * 3600,
            )

            stack, mocks = probes(is_running=True, idle_seconds=10_000.0, duration=None,
                                  image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, presence_managed=True)

            mocks["terminate"].assert_not_called()
            self.assertEqual(result.in_flight, "larkin/0 unsorted/busy.mp4")

    def test_headless_mode_leaves_a_present_users_encode_running(self):
        """Without presence management (the CLI passes it off), an in-flight
        encode is neither suspended nor started against — just supervised."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides)

            stack, mocks = probes(is_running=True, idle_seconds=5.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, presence_managed=False)

            mocks["suspend"].assert_not_called()
            self.assertEqual(result.in_flight, "larkin/0 unsorted/busy.mp4")
            self.assertFalse(result.suspended)


class TestThrottleToPresence(unittest.TestCase):
    """The fast between-ticks responder: suspend/resume the live encode alone,
    with no candidate scan or disk work, so a GUI timer can call it often."""

    def test_suspends_a_running_encode_when_the_user_returns(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides)

            stack, mocks = probes(is_running=True, idle_seconds=5.0)
            with override_config(**overrides), stack:
                changed = nonai_upscale.throttle_to_presence()

            self.assertEqual(changed, "suspended")
            mocks["suspend"].assert_called_once_with(4242)
            job = json.loads(overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertTrue(job["suspended"])

    def test_resumes_a_suspended_encode_when_the_user_idles_out(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, suspended=True, suspended_at=time.time() - 30)

            stack, mocks = probes(is_running=True, idle_seconds=10_000.0)
            with override_config(**overrides), stack:
                changed = nonai_upscale.throttle_to_presence()

            self.assertEqual(changed, "resumed")
            mocks["resume"].assert_called_once_with(4242)
            job = json.loads(overrides["NONAI_JOB_STATE_FILE"].read_text(encoding="utf-8"))
            self.assertFalse(job["suspended"])

    def test_no_change_when_presence_already_matches_state(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides)  # running, not suspended

            stack, mocks = probes(is_running=True, idle_seconds=10_000.0)
            with override_config(**overrides), stack:
                changed = nonai_upscale.throttle_to_presence()

            self.assertEqual(changed, "")
            mocks["suspend"].assert_not_called()
            mocks["resume"].assert_not_called()

    def test_does_nothing_without_a_live_job(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)

            stack, mocks = probes(idle_seconds=5.0)
            with override_config(**overrides), stack:
                changed = nonai_upscale.throttle_to_presence()

            self.assertEqual(changed, "")
            mocks["suspend"].assert_not_called()

    def test_ignores_a_job_whose_process_has_died(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides)

            stack, mocks = probes(is_running=False, idle_seconds=5.0)
            with override_config(**overrides), stack:
                changed = nonai_upscale.throttle_to_presence()

            self.assertEqual(changed, "")
            mocks["suspend"].assert_not_called()

    def test_a_poll_while_a_run_has_the_encode_in_hand_passes_at_once(self):
        """The poll runs on the window's thread, and a run starting an encode
        holds it for as long as its checks take: waiting there froze the
        window. The run applies presence itself, and the next poll is seconds
        away."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides)
            answered = []
            poll = threading.Thread(
                target=lambda: answered.append(nonai_upscale.throttle_to_presence()),
                daemon=True)

            stack, mocks = probes(is_running=True, idle_seconds=5.0)
            with override_config(**overrides), stack:
                nonai_upscale._throttle_lock.acquire()
                try:
                    poll.start()
                    poll.join(timeout=2)
                    passed_while_held = not poll.is_alive()
                finally:
                    nonai_upscale._throttle_lock.release()
                    poll.join(timeout=10)

            self.assertTrue(passed_while_held)
            self.assertEqual(answered, [""])
            mocks["suspend"].assert_not_called()


class TestEveryFileIsAParameter(unittest.TestCase):
    """The six files the stage touches are arguments, not ambient reads.

    Three it writes -- the job record, the attempt counter, the cooldown stamp
    -- and three the queue reads -- the skip and pin lists, and Fun Time's
    watch stats. Each threads through functions that decide whether a live
    encode is promoted, failed or killed, or which clip is started at all, so a
    parameter wired to the wrong place -- or resolved once at import, past
    ``override_config`` -- would leave the stage using the configured path
    anyway and nothing would say so. These point all six somewhere else and
    check both halves where there is a file to see: what the stage does follows
    the paths it was given, and the configured files stay untouched.
    """

    def test_a_start_writes_its_record_and_attempt_where_the_parameters_point(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            elsewhere = root / "elsewhere"
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            stack, _ = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(
                    allow_start=True,
                    job_file=elsewhere / "job.json",
                    attempts_file=elsewhere / "attempts.json",
                    cooldown_file=elsewhere / "cooldown.json",
                )

            self.assertEqual(result.started, "larkin/0 unsorted/a.mp4")
            self.assertTrue((elsewhere / "job.json").is_file())
            self.assertEqual(
                json.loads((elsewhere / "attempts.json").read_text(encoding="utf-8")),
                {"larkin/0 unsorted/a.mp4": 1},
            )
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())
            self.assertFalse(overrides["NONAI_ATTEMPTS_FILE"].exists())

    def test_a_conclusion_stamps_the_cooldown_file_the_parameter_names(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            elsewhere = root / "elsewhere"
            (overrides["NON_AI_DIR"] / "larkin" / "2 do not need work").mkdir(parents=True)
            write_job(root, overrides, expected=100.0, job_file=elsewhere / "job.json")

            stack, _ = probes(is_running=False, duration=99.5)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(
                    allow_start=False,
                    job_file=elsewhere / "job.json",
                    attempts_file=elsewhere / "attempts.json",
                    cooldown_file=elsewhere / "cooldown.json",
                )

            self.assertEqual(result.promoted, "larkin/0 unsorted/busy.mp4")
            self.assertIn(
                "ended_at",
                json.loads((elsewhere / "cooldown.json").read_text(encoding="utf-8")),
            )
            self.assertFalse(overrides["NONAI_COOLDOWN_FILE"].exists())

    def test_a_refused_start_is_recorded_in_the_skip_list_it_is_given(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")

            stack, _ = probes(videoai="apo8")  # already carries a Topaz tag
            with override_config(**overrides), stack:
                result = nonai_upscale.run(
                    allow_start=True,
                    job_file=elsewhere / "job.json",
                    attempts_file=elsewhere / "attempts.json",
                    cooldown_file=elsewhere / "cooldown.json",
                    skip_list=elsewhere / "skip.txt",
                    pin_list=elsewhere / "next.txt",
                    watch_stats_file=elsewhere / "watch.json",
                )

            self.assertEqual(result.started, "")
            self.assertEqual(
                (elsewhere / "skip.txt").read_text(encoding="utf-8").splitlines(),
                ["larkin/0 unsorted/a.mp4\talready carries a Topaz videoai tag"],
            )
            self.assertFalse(overrides["NONAI_SKIP_LIST"].exists())

    def test_the_pin_list_it_is_given_decides_which_clip_starts(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "larkin" / "0 unsorted" / "a.mp4")
            make_video(non_ai / "larkin" / "0 unsorted" / "z.mp4")
            (elsewhere / "next.txt").write_text(
                "larkin/0 unsorted/z.mp4\n", encoding="utf-8")

            stack, _ = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(
                    allow_start=True,
                    job_file=elsewhere / "job.json",
                    attempts_file=elsewhere / "attempts.json",
                    cooldown_file=elsewhere / "cooldown.json",
                    skip_list=elsewhere / "skip.txt",
                    pin_list=elsewhere / "next.txt",
                    watch_stats_file=elsewhere / "watch.json",
                )

            # Alphabetically "a" leads; only the pin puts "z" in front of it.
            self.assertEqual(result.started, "larkin/0 unsorted/z.mp4")

    def test_the_watch_stats_file_it_is_given_decides_which_clip_starts(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "larkin" / "0 unsorted" / "a.mp4")
            watched = make_video(non_ai / "larkin" / "0 unsorted" / "z.mp4")
            (elsewhere / "watch.json").write_text(json.dumps({
                str(watched).lower(): {"completions": 5, "skips": 0, "locks": 0},
            }), encoding="utf-8")

            stack, _ = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(
                    allow_start=True,
                    job_file=elsewhere / "job.json",
                    attempts_file=elsewhere / "attempts.json",
                    cooldown_file=elsewhere / "cooldown.json",
                    skip_list=elsewhere / "skip.txt",
                    pin_list=elsewhere / "next.txt",
                    watch_stats_file=elsewhere / "watch.json",
                )

            self.assertEqual(result.started, "larkin/0 unsorted/z.mp4")

    def test_the_presence_throttle_parks_the_job_file_it_is_given(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            elsewhere = root / "elsewhere"
            write_job(root, overrides, job_file=elsewhere / "job.json")

            stack, mocks = probes(is_running=True, idle_seconds=5.0)
            with override_config(**overrides), stack:
                changed = nonai_upscale.throttle_to_presence(
                    job_file=elsewhere / "job.json")

            self.assertEqual(changed, "suspended")
            mocks["suspend"].assert_called_once_with(4242)
            job = json.loads((elsewhere / "job.json").read_text(encoding="utf-8"))
            self.assertTrue(job["suspended"])
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())


class TestPortraitTargets(unittest.TestCase):
    def test_portrait_video_gets_swapped_target_edges(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "tall.mp4")

            stack, mocks = probes(orientation="portrait")
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=True)

            cmd = mocks["popen"].call_args.args[0]
            filter_arg = cmd[cmd.index("-filter_complex") + 1]
            self.assertIn("w=2160:h=3840", filter_arg)


class TestRunSupervisesAJob(unittest.TestCase):
    def test_live_job_reports_in_flight_and_blocks_new_starts(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, tmp, _ = write_job(root, overrides)
            make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "next.mp4")

            stack, mocks = probes(is_running=True)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.in_flight, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.started, "")
            mocks["popen"].assert_not_called()
            self.assertTrue(tmp.exists())
            self.assertTrue(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_live_job_reports_percent_encoded_so_far(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, expected=200.0)

            stack, _ = probes(is_running=True, duration=75.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.in_flight_percent, 38)  # 75/200, rounded

    def test_live_job_percent_is_none_when_the_partial_is_unreadable(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, expected=200.0)

            stack, _ = probes(is_running=True, duration=None)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.in_flight, "larkin/0 unsorted/busy.mp4")
            self.assertIsNone(result.in_flight_percent)

    def test_finished_job_is_promoted_and_the_original_retired(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            retire_dir = non_ai / "larkin" / "2 do not need work"
            retire_dir.mkdir(parents=True)
            source, tmp, out = write_job(root, overrides, expected=100.0)

            stack, _mocks = probes(is_running=False, duration=99.5)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.promoted, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.failed, "")
            self.assertTrue(out.exists())
            self.assertFalse(tmp.exists())
            self.assertFalse(source.exists())
            self.assertTrue((retire_dir / "busy.mp4").exists())
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_promote_without_a_retire_dir_leaves_the_original_in_place(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            source, _tmp, out = write_job(root, overrides, expected=100.0)

            stack, _ = probes(is_running=False, duration=100.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.promoted, "larkin/0 unsorted/busy.mp4")
            self.assertTrue(out.exists())
            self.assertTrue(source.exists())

    def test_short_output_counts_as_failure_and_is_retried(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            source, tmp, out = write_job(root, overrides, expected=100.0)

            stack, _mocks = probes(is_running=False, duration=42.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.failed, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.promoted, "")
            self.assertFalse(out.exists())
            self.assertFalse(tmp.exists())
            self.assertTrue(source.exists())
            self.assertFalse(overrides["NONAI_SKIP_LIST"].exists())
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_a_final_failed_attempt_lands_in_the_skip_list(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, _tmp, _out = write_job(root, overrides, expected=100.0)
            overrides["NONAI_ATTEMPTS_FILE"].write_text(
                json.dumps({"larkin/0 unsorted/busy.mp4": nonai_encode.EncodeSettings().max_attempts}),
                encoding="utf-8",
            )

            stack, _mocks = probes(is_running=False, duration=None)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.failed, "larkin/0 unsorted/busy.mp4")
            skip_list = overrides["NONAI_SKIP_LIST"].read_text(encoding="utf-8")
            self.assertIn("larkin/0 unsorted/busy.mp4\t", skip_list)
            attempts = json.loads(overrides["NONAI_ATTEMPTS_FILE"].read_text(encoding="utf-8"))
            self.assertNotIn("larkin/0 unsorted/busy.mp4", attempts)

    def test_overrunning_ffmpeg_is_terminated_and_concluded(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, _tmp, _out = write_job(
                root, overrides,
                started_seconds_ago=nonai_encode.EncodeSettings().max_runtime_hours * 3600 + 60,
            )

            stack, mocks = probes(is_running=True, duration=1.0,
                                  image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            mocks["terminate"].assert_called_once_with(4242)
            self.assertEqual(result.failed, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.in_flight, "")
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_a_concluded_encode_stamps_the_cooldown_but_a_user_stop_does_not(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(root, overrides, expected=100.0)

            stack, _ = probes(is_running=False, duration=100.0)
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=False)
            self.assertTrue(overrides["NONAI_COOLDOWN_FILE"].exists())

            overrides["NONAI_COOLDOWN_FILE"].unlink()
            write_job(root, overrides)
            stack, _ = probes(is_running=True, image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=False, stop=True)
            self.assertFalse(overrides["NONAI_COOLDOWN_FILE"].exists())

    def test_low_disk_mid_flight_stops_the_encode_without_penalty(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, tmp, _out = write_job(root, overrides)

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG), free_bytes=1)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            mocks["terminate"].assert_called_once_with(4242)
            self.assertTrue(result.deferred_low_disk)
            self.assertEqual(result.stopped, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.failed, "")
            self.assertFalse(tmp.exists())
            self.assertFalse(overrides["NONAI_SKIP_LIST"].exists())
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_orphaned_partials_are_swept_but_the_live_jobs_tmp_survives(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, tmp, out = write_job(root, overrides)
            orphan = partial_path(out, "old")
            orphan.write_bytes(b"partial")

            stack, _ = probes(is_running=True)
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=False)

            self.assertFalse(orphan.exists())
            self.assertTrue(tmp.exists())

    def test_recycled_pid_is_never_terminated(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            write_job(
                root, overrides,
                started_seconds_ago=nonai_encode.EncodeSettings().max_runtime_hours * 3600 + 60,
            )

            stack, mocks = probes(is_running=True, duration=1.0,
                                  image=r"C:\Windows\notepad.exe")
            with override_config(**overrides), stack:
                nonai_upscale.run(allow_start=False)

            mocks["terminate"].assert_not_called()


class TestPromotionCarriesTheRecord(unittest.TestCase):
    """What the upscale must be handed before its original leaves the library.

    The move itself is :mod:`util.nonai_retire`'s and tested there; these are
    the stage's half — that promotion does the carry at all, and before the
    retire rather than after.
    """

    def test_the_upscale_keeps_the_clip_record_the_original_takes_away(self):
        """Promotion must hand the upscale its own copy first, or the record goes.

        The `clip` object naming which compilation a video was carved out of is
        what marks it a cut at all, and it lived only on the original — which
        retirement moves out of the library. The grouping stage would copy one
        across from an in-library original, but it runs later in the same pass
        and by then there is none, so an upscaled cut arrived in the library as
        an anonymous whole video, filed among the very scenes it was cut from.
        """
        with workspace_temp_dir() as root:
            archive = root / "archive"
            overrides = library_overrides(root, NONAI_RETIRED_ROOT=archive)
            source, _tmp, out = write_job(
                root, overrides, expected=100.0,
                source=make_video(
                    overrides["NON_AI_DIR"] / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4"
                ),
            )

            stack, _mocks = probes(is_running=False, duration=100.0)
            with override_config(**overrides), stack:
                write_sidecar(sidecar.sidecar_path(source), {
                    "version": {"group": "Lee-Poe", "processed": False},
                    "video": {"action": "alpha"},
                    "clip": {"compilation": "Volume One", "index": 1, "count": 4},
                })

                nonai_upscale.run(allow_start=False)

                carried = sidecar.read(sidecar.sidecar_path(out))
            self.assertEqual(carried["clip"],
                             {"compilation": "Volume One", "index": 1, "count": 4})
            self.assertEqual(carried["video"], {"action": "alpha"})

    def test_the_carried_sidecar_leaves_the_version_block_alone(self):
        """`version` describes the file, not the footage — the original is not a
        processed variant and the upscale is, and the grouping stage is the one
        thing that gets to say so."""
        with workspace_temp_dir() as root:
            archive = root / "archive"
            overrides = library_overrides(root, NONAI_RETIRED_ROOT=archive)
            source, _tmp, out = write_job(
                root, overrides, expected=100.0,
                source=make_video(
                    overrides["NON_AI_DIR"] / "larkin" / "1 clips to upscale" / "Lee-Poe.mp4"
                ),
            )

            stack, _mocks = probes(is_running=False, duration=100.0)
            with override_config(**overrides), stack:
                write_sidecar(sidecar.sidecar_path(source), {
                    "version": {"group": "Lee-Poe", "processed": False},
                    "clip": {"compilation": "Volume One", "index": 1},
                })

                nonai_upscale.run(allow_start=False)

                self.assertNotIn("version", sidecar.read(sidecar.sidecar_path(out)))


class TestReportingHowFarAlongItIs(unittest.TestCase):
    """The stage says how much of the project is left, not just how many clips.

    The arithmetic is :mod:`tasks.nonai_progress`'s; what is checked here is
    that the queue the stage reports on and the queue it weighs are the same
    one, and that the numbers reach the result the window reads.
    """

    def _lasting(self, video, seconds):
        path = sidecar.sidecar_path(video)
        write_sidecar(path, video_type.timed(sidecar.read(path), seconds))
        return video

    def test_reports_the_percentage_and_the_hours_left_beside_the_count(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            stack, _ = probes()
            with override_config(**overrides), stack:
                self._lasting(
                    make_video(non_ai / "larkin" / "0 unsorted" / "queued.mp4"), 900.0)
                self._lasting(
                    make_video(non_ai / "larkin" / "3_good_to_go" / "processed"
                               / "older_apo8_iris2.mp4"), 300.0)

                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.pending, 1)
            self.assertEqual(result.remaining_seconds, 900.0)
            self.assertEqual(result.percent_complete, 25)
            self.assertEqual(result.unmeasured_videos, 0)

    def test_a_clip_retired_to_the_skip_list_leaves_both_the_count_and_the_hours(self):
        """The queue is collected again after a start attempt for exactly this
        reason, and the running times have to come off that same collection."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            stack, mocks = probes()
            mocks["videoai"].side_effect = ["Enhanced using iris-2", ""]
            with override_config(**overrides), stack:
                self._lasting(
                    make_video(non_ai / "larkin" / "0 unsorted" / "a tagged.mp4"), 3600.0)
                self._lasting(
                    make_video(non_ai / "larkin" / "0 unsorted" / "b fresh.mp4"), 900.0)

                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "larkin/0 unsorted/b fresh.mp4")
            self.assertEqual(result.pending, 1)
            self.assertEqual(result.remaining_seconds, 900.0)

    def test_a_library_nothing_has_measured_yet_has_no_percentage(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            make_video(non_ai / "larkin" / "0 unsorted" / "unmeasured.mp4")

            stack, _ = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.pending, 1)
            self.assertIsNone(result.percent_complete)
            self.assertEqual(result.unmeasured_videos, 1)


if __name__ == "__main__":
    unittest.main()
