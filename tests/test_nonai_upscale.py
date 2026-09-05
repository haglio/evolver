import json
import subprocess
import time
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import config
from tasks import nonai_upscale
from tests.temp_helpers import (
    make_video,
    override_config,
    workspace_temp_dir,
)
from tests.temp_helpers import (
    nonai_library_overrides as library_overrides,
)
from util import sidecar, video_type


def write_job(root, overrides, *, pid=4242, started_seconds_ago=60.0, expected=100.0,
              source=None, tmp_bytes=b"partial", suspended=False, suspended_at=0.0,
              suspended_seconds=0.0, job_file=None):
    """A persisted in-flight job whose tmp file exists under the bucket.

    *job_file* writes the record somewhere other than the configured path, which
    is how the tests for the state-file parameters put the record where only a
    caller passing that path could find it.
    """
    non_ai = overrides["NON_AI_DIR"]
    source = source or make_video(non_ai / "larkin" / "0 unsorted" / "busy.mp4")
    out = non_ai / "larkin" / "3_good_to_go" / "processed" / f"{source.stem}_apo8_iris2.mp4"
    tmp = out.with_name(f"{source.stem}.partial.abc123.mp4")
    if tmp_bytes is not None:
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(tmp_bytes)
    job = {
        "pid": pid,
        "source": str(source),
        "tmp": str(tmp),
        "out": str(out),
        "expected_duration": expected,
        "started_at": time.time() - started_seconds_ago,
        "suspended": suspended,
        "suspended_at": suspended_at,
        "suspended_seconds": suspended_seconds,
    }
    job_file = job_file or overrides["NONAI_JOB_STATE_FILE"]
    job_file.parent.mkdir(parents=True, exist_ok=True)
    job_file.write_text(json.dumps(job), encoding="utf-8")
    return source, tmp, out


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
            patch("util.ffprobe.get_orientation", return_value=orientation)),
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

    def test_already_tagged_candidate_is_manifested_and_the_next_one_starts(self):
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
            manifest = overrides["NONAI_SKIP_MANIFEST"].read_text(encoding="utf-8")
            self.assertIn("larkin/0 unsorted/a tagged.mp4\t", manifest)

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

    def test_an_idled_out_user_allows_the_start(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            self._one_candidate(overrides)

            stack, _mocks = probes(
                idle_seconds=config.NONAI_USER_IDLE_THRESHOLD_SECONDS + 60)
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
                json.dumps({"ended_at": time.time() - config.NONAI_COOLDOWN_MINUTES * 60 - 60}),
                encoding="utf-8",
            )

            stack, _mocks = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "larkin/0 unsorted/a.mp4")
            self.assertEqual(result.start_deferred, "")


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
            self.assertFalse(overrides["NONAI_SKIP_MANIFEST"].exists())

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
JOB_KEYS_AT_START = {"pid", "source", "tmp", "out", "expected_duration", "started_at"}
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

    def test_an_adopted_encode_writes_exactly_these(self):
        from util import topaz
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "0 unsorted" / "busy.mp4")
            tmp = (non_ai / "larkin" / "3_good_to_go" / "processed"
                   / "busy.partial.deadbeefcafe.mp4")
            make_video(tmp)
            cmdline = subprocess.list2cmdline(
                topaz.command(source, tmp, "the-filter", "the-tag", keep_audio=True)
            )

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


class TestOrphanAdoption(unittest.TestCase):
    """A lost job file must not orphan a live encode.

    The file sync service covering the project tree renamed the in-flight job
    file to '... [conflicted N].json' mid-run; the stage then saw no job, the
    running ffmpeg went unsupervised, and fresh starts stacked encodes until
    the machine crashed. With the state file gone, a lone Topaz process is
    re-identified from its own command line and adopted back under supervision.
    """

    def test_a_lone_topaz_process_is_adopted_back_into_a_job(self):
        from util import topaz
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source = make_video(non_ai / "larkin" / "0 unsorted" / "busy.mp4")
            processed = non_ai / "larkin" / "3_good_to_go" / "processed"
            tmp = processed / "busy.partial.deadbeefcafe.mp4"
            make_video(tmp)
            cmdline = subprocess.list2cmdline(
                topaz.command(source, tmp, "the-filter", "the-tag", keep_audio=True)
            )

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
                started_seconds_ago=config.NONAI_MAX_RUNTIME_HOURS * 3600 + 3600,
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


class TestEveryFileIsAParameter(unittest.TestCase):
    """The six files the stage touches are arguments, not ambient reads.

    Three it writes -- the job record, the attempt counter, the cooldown stamp
    -- and three the queue reads -- the skip and pin manifests, and Fun Time's
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

    def test_a_refused_start_is_recorded_in_the_skip_manifest_it_is_given(self):
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
                    skip_manifest=elsewhere / "skip.txt",
                    pin_manifest=elsewhere / "next.txt",
                    watch_stats_file=elsewhere / "watch.json",
                )

            self.assertEqual(result.started, "")
            self.assertEqual(
                (elsewhere / "skip.txt").read_text(encoding="utf-8").splitlines(),
                ["larkin/0 unsorted/a.mp4\talready carries a Topaz videoai tag"],
            )
            self.assertFalse(overrides["NONAI_SKIP_MANIFEST"].exists())

    def test_the_pin_manifest_it_is_given_decides_which_clip_starts(self):
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
                    skip_manifest=elsewhere / "skip.txt",
                    pin_manifest=elsewhere / "next.txt",
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
                    skip_manifest=elsewhere / "skip.txt",
                    pin_manifest=elsewhere / "next.txt",
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
            self.assertFalse(overrides["NONAI_SKIP_MANIFEST"].exists())
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_final_failed_attempt_lands_in_the_skip_manifest(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, _tmp, _out = write_job(root, overrides, expected=100.0)
            overrides["NONAI_ATTEMPTS_FILE"].write_text(
                json.dumps({"larkin/0 unsorted/busy.mp4": config.NONAI_MAX_ATTEMPTS}),
                encoding="utf-8",
            )

            stack, _mocks = probes(is_running=False, duration=None)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.failed, "larkin/0 unsorted/busy.mp4")
            manifest = overrides["NONAI_SKIP_MANIFEST"].read_text(encoding="utf-8")
            self.assertIn("larkin/0 unsorted/busy.mp4\t", manifest)
            attempts = json.loads(overrides["NONAI_ATTEMPTS_FILE"].read_text(encoding="utf-8"))
            self.assertNotIn("larkin/0 unsorted/busy.mp4", attempts)

    def test_overrunning_ffmpeg_is_terminated_and_concluded(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            _source, _tmp, _out = write_job(
                root, overrides,
                started_seconds_ago=config.NONAI_MAX_RUNTIME_HOURS * 3600 + 60,
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
            self.assertFalse(overrides["NONAI_SKIP_MANIFEST"].exists())
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_orphaned_partials_are_swept_but_the_live_jobs_tmp_survives(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            _source, tmp, _ = write_job(root, overrides)
            orphan = make_video(
                non_ai / "larkin" / "3_good_to_go" / "processed" / "old.partial.dead.mp4"
            )

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
                started_seconds_ago=config.NONAI_MAX_RUNTIME_HOURS * 3600 + 60,
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
                sidecar.write(sidecar.sidecar_path(source), {
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
                sidecar.write(sidecar.sidecar_path(source), {
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
        sidecar.write(path, video_type.timed(sidecar.read(path), seconds))
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

    def test_a_clip_retired_to_the_skip_manifest_leaves_both_the_count_and_the_hours(self):
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
