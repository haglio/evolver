import json
import subprocess
import time
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import config
from tasks import nonai_upscale
from tests.temp_helpers import override_config, workspace_temp_dir


def make_video(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    return path


def library_overrides(root, **extra):
    """Config overrides mapping a temp tree shaped like the real library."""
    video_lib = root / "videos"
    overrides = dict(
        VIDEO_LIBRARY_DIR=video_lib,
        NON_AI_DIR=video_lib / "2D" / "non_AI",
        SCRIPT_LIBRARY_DIR=root / "scripts",
        NONAI_SKIP_MANIFEST=root / "skip.txt",
        NONAI_JOB_STATE_FILE=root / "job.json",
        NONAI_ATTEMPTS_FILE=root / "attempts.json",
        NONAI_COOLDOWN_FILE=root / "cooldown.json",
        NONAI_FFMPEG_LOG=root / "ffmpeg.log",
        FUN_TIME_WATCH_STATS_FILE=root / "watch_stats.json",
    )
    overrides.update(extra)
    return overrides


class TestCollectCandidates(unittest.TestCase):
    def test_finds_unprocessed_videos_in_triage_dirs_only(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            unsorted_video = make_video(non_ai / "larkin" / "0 unsorted" / "a.mp4")
            flagged_video = make_video(non_ai / "other" / "1 could use work" / "b.mp4")
            make_video(non_ai / "larkin" / "2 do not need work" / "retired.mp4")
            make_video(non_ai / "larkin" / "3_good_to_go" / "processed" / "done_iris2.mp4")
            make_video(non_ai / "actually_AI_but_funscripted" / "0 unsorted" / "ai.mp4")

            with override_config(**overrides):
                candidates = nonai_upscale.collect_candidates()

            self.assertEqual(
                sorted(c.path for c in candidates), [flagged_video, unsorted_video]
            )

    def test_ignores_videos_nested_in_triage_subfolders(self):
        """A subfolder inside a triage dir stages manual pre-work (e.g. larkin
        '1 could use work/1_originals_needing_trimming'); those clips are not
        ready for an unattended multi-hour encode."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            ready = make_video(non_ai / "larkin" / "1 could use work" / "ready.mp4")
            make_video(
                non_ai / "larkin" / "1 could use work"
                / "1_originals_needing_trimming" / "not yet.mp4"
            )

            with override_config(**overrides):
                candidates = nonai_upscale.collect_candidates()

            self.assertEqual([c.path for c in candidates], [ready])

    def test_excludes_originals_that_already_have_a_processed_variant(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            make_video(non_ai / "other" / "0 unsorted" / "kina.mp4")
            make_video(non_ai / "other" / "0 unsorted" / "kina_apo8_prob4.mp4")
            make_video(non_ai / "other" / "0 unsorted" / "lily.mp4")
            make_video(non_ai / "other" / "3 good to go" / "processed" / "lily_iris2.mp4")
            fresh = make_video(non_ai / "other" / "0 unsorted" / "fresh.mp4")

            with override_config(**overrides):
                candidates = nonai_upscale.collect_candidates()

            self.assertEqual([c.path for c in candidates], [fresh])

    def test_excludes_skip_manifest_entries(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            make_video(non_ai / "other" / "0 unsorted" / "hopeless.mp4")
            fresh = make_video(non_ai / "other" / "0 unsorted" / "fresh.mp4")
            overrides["NONAI_SKIP_MANIFEST"].write_text(
                "other/0 unsorted/hopeless.mp4\tfailed twice\n", encoding="utf-8"
            )

            with override_config(**overrides):
                candidates = nonai_upscale.collect_candidates()

            self.assertEqual([c.path for c in candidates], [fresh])

    def test_watched_videos_outrank_funscripted_ones(self):
        """Fun Time's watch stats (once its Nau tracking records them) are the
        strongest popularity signal; funscripts break ties among the unwatched."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            watched = make_video(non_ai / "larkin" / "0 unsorted" / "watched.mp4")
            scripted = make_video(non_ai / "larkin" / "0 unsorted" / "scripted.mp4")
            plain = make_video(non_ai / "larkin" / "0 unsorted" / "plain.mp4")
            disliked = make_video(non_ai / "larkin" / "0 unsorted" / "disliked.mp4")
            script = overrides["SCRIPT_LIBRARY_DIR"] / "2D" / "non_AI" / "larkin" / "0 unsorted" / "scripted.funscript"
            script.parent.mkdir(parents=True)
            script.write_text("{}", encoding="utf-8")
            overrides["FUN_TIME_WATCH_STATS_FILE"].write_text(json.dumps({
                str(watched).lower(): {"completions": 4, "skips": 0, "locks": 1},
                str(disliked).lower(): {"completions": 0, "skips": 3, "locks": 0},
            }), encoding="utf-8")

            with override_config(**overrides):
                candidates = nonai_upscale.collect_candidates()

            self.assertEqual(
                [c.path for c in candidates], [watched, scripted, plain, disliked]
            )

    def test_orders_flagged_then_funscripted_then_the_rest(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            plain = make_video(non_ai / "larkin" / "0 unsorted" / "aaa plain.mp4")
            scripted = make_video(non_ai / "larkin" / "0 unsorted" / "zzz scripted.mp4")
            flagged = make_video(non_ai / "larkin" / "1 could use work" / "flagged.mp4")
            script = overrides["SCRIPT_LIBRARY_DIR"] / "2D" / "non_AI" / "larkin" / "0 unsorted" / "zzz scripted.funscript"
            script.parent.mkdir(parents=True)
            script.write_text("{}", encoding="utf-8")

            with override_config(**overrides):
                candidates = nonai_upscale.collect_candidates()

            self.assertEqual([c.path for c in candidates], [flagged, scripted, plain])


def write_job(root, overrides, *, pid=4242, started_seconds_ago=60.0, expected=100.0,
              source=None, tmp_bytes=b"partial", suspended=False, suspended_at=0.0,
              suspended_seconds=0.0):
    """A persisted in-flight job whose tmp file exists under the bucket."""
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
    overrides["NONAI_JOB_STATE_FILE"].parent.mkdir(parents=True, exist_ok=True)
    overrides["NONAI_JOB_STATE_FILE"].write_text(json.dumps(job), encoding="utf-8")
    return source, tmp, out


def probes(videoai="", orientation="landscape", duration=100.0, free_bytes=10**15,
           popen=None, is_running=True, image="ffmpeg.exe", terminate=True,
           topaz_pids=(), cmdline=None, available_ram=64.0, idle_seconds=10_000.0):
    """An ExitStack patching every outside contact the stage makes.

    idle_seconds defaults to a long idle (the user is away), so the presence
    throttle lets encodes start unless a test says otherwise.
    """
    stack = ExitStack()
    mocks = {
        "idle_seconds": stack.enter_context(
            patch("tasks.nonai_upscale.system_resources.seconds_since_last_input",
                  return_value=idle_seconds)),
        "suspend": stack.enter_context(
            patch("tasks.nonai_upscale.processes.suspend", return_value=True)),
        "resume": stack.enter_context(
            patch("tasks.nonai_upscale.processes.resume", return_value=True)),
        "videoai": stack.enter_context(
            patch("tasks.nonai_upscale.ffprobe.videoai_tag", return_value=videoai)),
        "orientation": stack.enter_context(
            patch("tasks.nonai_upscale.ffprobe.get_orientation", return_value=orientation)),
        "duration": stack.enter_context(
            patch("tasks.nonai_upscale.ffprobe.duration_seconds", return_value=duration)),
        "free_bytes": stack.enter_context(
            patch("tasks.nonai_upscale.system_resources.free_bytes", return_value=free_bytes)),
        "available_ram": stack.enter_context(
            patch("tasks.nonai_upscale.system_resources.available_ram_gb", return_value=available_ram)),
        "popen": stack.enter_context(
            patch("tasks.nonai_upscale.subprocess.Popen", popen or Mock(return_value=Mock(pid=4242)))),
        "is_running": stack.enter_context(
            patch("tasks.nonai_upscale.processes.is_running", return_value=is_running)),
        "image_path": stack.enter_context(
            patch("tasks.nonai_upscale.processes.image_path", return_value=image)),
        "terminate": stack.enter_context(
            patch("tasks.nonai_upscale.processes.terminate", return_value=terminate)),
        "pids_of_image": stack.enter_context(
            patch("tasks.nonai_upscale.processes.pids_of_image", return_value=list(topaz_pids))),
        "command_line": stack.enter_context(
            patch("tasks.nonai_upscale.processes.command_line", return_value=cmdline)),
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

            stack, mocks = probes(
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

            stack, mocks = probes()
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            self.assertEqual(result.started, "larkin/0 unsorted/a.mp4")
            self.assertEqual(result.start_deferred, "")


class TestRunStopsAJob(unittest.TestCase):
    def test_stop_kills_the_running_encode_without_penalizing_the_video(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            source, tmp, out = write_job(root, overrides)
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
            self.assertEqual(result.failed, 0)
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
            source, tmp, out = write_job(root, overrides, expected=100.0)

            stack, mocks = probes(is_running=False, duration=100.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False, stop=True)

            mocks["terminate"].assert_not_called()
            self.assertEqual(result.promoted, "larkin/0 unsorted/busy.mp4")
            self.assertTrue(out.exists())


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
            source, tmp, _ = write_job(root, overrides)

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
            source, tmp, _ = write_job(root, overrides)
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

            stack, mocks = probes(is_running=False, duration=99.5)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.promoted, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.failed, 0)
            self.assertTrue(out.exists())
            self.assertFalse(tmp.exists())
            self.assertFalse(source.exists())
            self.assertTrue((retire_dir / "busy.mp4").exists())
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_promote_without_a_retire_dir_leaves_the_original_in_place(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            source, tmp, out = write_job(root, overrides, expected=100.0)

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

            stack, mocks = probes(is_running=False, duration=42.0)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.failed, 1)
            self.assertEqual(result.promoted, "")
            self.assertFalse(out.exists())
            self.assertFalse(tmp.exists())
            self.assertTrue(source.exists())
            self.assertFalse(overrides["NONAI_SKIP_MANIFEST"].exists())
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_final_failed_attempt_lands_in_the_skip_manifest(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            source, tmp, out = write_job(root, overrides, expected=100.0)
            overrides["NONAI_ATTEMPTS_FILE"].write_text(
                json.dumps({"larkin/0 unsorted/busy.mp4": config.NONAI_MAX_ATTEMPTS}),
                encoding="utf-8",
            )

            stack, mocks = probes(is_running=False, duration=None)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            self.assertEqual(result.failed, 1)
            manifest = overrides["NONAI_SKIP_MANIFEST"].read_text(encoding="utf-8")
            self.assertIn("larkin/0 unsorted/busy.mp4\t", manifest)
            attempts = json.loads(overrides["NONAI_ATTEMPTS_FILE"].read_text(encoding="utf-8"))
            self.assertNotIn("larkin/0 unsorted/busy.mp4", attempts)

    def test_overrunning_ffmpeg_is_terminated_and_concluded(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            source, tmp, out = write_job(
                root, overrides,
                started_seconds_ago=config.NONAI_MAX_RUNTIME_HOURS * 3600 + 60,
            )

            stack, mocks = probes(is_running=True, duration=1.0,
                                  image=str(config.FFMPEG))
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=False)

            mocks["terminate"].assert_called_once_with(4242)
            self.assertEqual(result.failed, 1)
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
            source, tmp, out = write_job(root, overrides)

            stack, mocks = probes(is_running=True, image=str(config.FFMPEG), free_bytes=1)
            with override_config(**overrides), stack:
                result = nonai_upscale.run(allow_start=True)

            mocks["terminate"].assert_called_once_with(4242)
            self.assertTrue(result.deferred_low_disk)
            self.assertEqual(result.stopped, "larkin/0 unsorted/busy.mp4")
            self.assertEqual(result.failed, 0)
            self.assertFalse(tmp.exists())
            self.assertFalse(overrides["NONAI_SKIP_MANIFEST"].exists())
            self.assertFalse(overrides["NONAI_JOB_STATE_FILE"].exists())

    def test_orphaned_partials_are_swept_but_the_live_jobs_tmp_survives(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            source, tmp, _ = write_job(root, overrides)
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


if __name__ == "__main__":
    unittest.main()
