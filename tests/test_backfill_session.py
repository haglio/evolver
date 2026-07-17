import json
import random
import unittest
from pathlib import Path
from unittest.mock import patch

from backfill.queue import BackfillQueue
from backfill.session import BackfillSession
from tests.temp_helpers import override_config, workspace_temp_dir
from util.sidecar import sidecar_path


class ImmediateWorker:
    """Stands in for SerialWorker: runs each task at once, so drain has nothing to do."""

    def __init__(self):
        self.drained = 0

    def submit(self, task):
        task()

    def drain(self):
        self.drained += 1


class DeferredWorker:
    """Holds tasks until drained, so a test can watch the ordering undo relies on."""

    def __init__(self):
        self.pending = []

    def submit(self, task):
        self.pending.append(task)

    def drain(self):
        while self.pending:
            self.pending.pop(0)()


class TestBackfillSession(unittest.TestCase):
    def _session(self, count=3, worker=None):
        videos = [Path(f"clip{i}.mp4") for i in range(count)]
        queue = BackfillQueue(videos, rng=random.Random(0))
        return BackfillSession(queue, worker or ImmediateWorker())

    def test_an_act_records_the_action_against_the_clip_on_screen(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.sidecar_snapshot"):
            note = session.apply("side gamma")

        record.assert_called_once_with(clip, "Side Gamma")
        self.assertEqual(note, f"{clip.name} → Side Gamma")

    def test_an_act_retires_the_clip(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action"), patch("backfill.session.sidecar_snapshot"):
            session.apply("dance")

        self.assertEqual(session.remaining, 2)
        self.assertNotEqual(session.current, clip)

    def test_skip_defers_the_clip_without_touching_the_disk(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.discard_as_weird") as discard:
            note = session.apply("skip")

        record.assert_not_called()
        discard.assert_not_called()
        self.assertEqual(note, f"{clip.name} → skipped")
        self.assertEqual(session.remaining, 3)
        self.assertNotEqual(session.current, clip)

    def test_weird_discards_the_clip_and_writes_no_metadata(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.discard_as_weird") as discard:
            note = session.apply("trash")

        discard.assert_called_once_with(clip)
        record.assert_not_called()
        self.assertEqual(note, f"{clip.name} → weird")
        self.assertEqual(session.remaining, 2)

    def test_an_unknown_phrase_leaves_the_clip_on_screen(self):
        session = self._session()
        clip = session.current

        note = session.apply("banana")

        self.assertIsNone(note)
        self.assertEqual(session.current, clip)
        self.assertEqual(session.remaining, 3)

    def test_a_phrase_heard_after_the_last_clip_does_nothing(self):
        session = self._session(count=1)

        with patch("backfill.session.record_action"), patch("backfill.session.sidecar_snapshot"):
            session.apply("dance")
            note = session.apply("dance")

        self.assertIsNone(note)
        self.assertIsNone(session.current)

    def test_the_clip_advances_before_the_file_work_runs(self):
        worker = DeferredWorker()
        session = self._session(worker=worker)
        clip = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.sidecar_snapshot"):
            session.apply("dance")

            record.assert_not_called()
            self.assertNotEqual(session.current, clip)

            worker.drain()
            record.assert_called_once_with(clip, "Dancing")


class TestUndo(unittest.TestCase):
    def _session(self, count=3, worker=None):
        videos = [Path(f"clip{i}.mp4") for i in range(count)]
        queue = BackfillQueue(videos, rng=random.Random(0))
        return BackfillSession(queue, worker or ImmediateWorker())

    def test_undo_with_nothing_decided_says_so_and_changes_nothing(self):
        session = self._session()
        clip = session.current

        note = session.apply("undo")

        self.assertEqual(note, "nothing to undo")
        self.assertEqual(session.current, clip)
        self.assertEqual(session.remaining, 3)

    def test_undoing_an_act_puts_the_clip_back_and_removes_its_sidecar(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action"), \
             patch("backfill.session.sidecar_snapshot", return_value=None), \
             patch("backfill.session.restore_sidecar") as restore:
            session.apply("dance")
            note = session.apply("undo")

        restore.assert_called_once_with(clip, None)
        self.assertEqual(note, f"undid {clip.name} → Dancing")
        self.assertEqual(session.current, clip)
        self.assertEqual(session.remaining, 3)

    def test_undoing_a_discard_reclaims_the_clip_from_the_weird_folder(self):
        session = self._session()
        clip = session.current
        landed = Path("kinda_weird") / clip.name

        with patch("backfill.session.discard_as_weird", return_value=landed), \
             patch("backfill.session.reclaim_from_weird") as reclaim:
            session.apply("weird")
            note = session.apply("undo")

        reclaim.assert_called_once_with(landed, clip)
        self.assertEqual(note, f"undid {clip.name} → weird")
        self.assertEqual(session.current, clip)
        self.assertEqual(session.remaining, 3)

    def test_undoing_a_skip_brings_the_deferred_clip_back(self):
        session = self._session()
        clip = session.current

        session.apply("skip")
        note = session.apply("undo")

        self.assertEqual(note, f"undid {clip.name} → skipped")
        self.assertEqual(session.current, clip)
        self.assertEqual(session.remaining, 3)

    def test_undo_works_after_the_final_clip_has_been_labelled(self):
        session = self._session(count=1)
        clip = session.current

        with patch("backfill.session.record_action"), \
             patch("backfill.session.sidecar_snapshot", return_value=None), \
             patch("backfill.session.restore_sidecar"):
            session.apply("dance")
            self.assertIsNone(session.current)
            session.apply("undo")

        self.assertEqual(session.current, clip)
        self.assertEqual(session.remaining, 1)

    def test_undo_waits_for_the_decision_it_is_about_to_reverse(self):
        worker = DeferredWorker()
        session = self._session(worker=worker)
        order = []

        with patch("backfill.session.record_action", side_effect=lambda *_: order.append("record")), \
             patch("backfill.session.sidecar_snapshot", return_value=None), \
             patch("backfill.session.restore_sidecar", side_effect=lambda *_: order.append("restore")):
            session.apply("dance")
            session.apply("undo")

        self.assertEqual(order, ["record", "restore"])

    def test_undo_steps_back_through_a_run_of_decisions(self):
        session = self._session(count=4)
        with patch("backfill.session.record_action"), \
             patch("backfill.session.sidecar_snapshot", return_value=None), \
             patch("backfill.session.restore_sidecar"), \
             patch("backfill.session.discard_as_weird", return_value=Path("w.mp4")), \
             patch("backfill.session.reclaim_from_weird"):
            first, second = session.current, None
            session.apply("dance")
            second = session.current
            session.apply("weird")
            third = session.current
            session.apply("skip")

            self.assertEqual(session.apply("undo"), f"undid {third.name} → skipped")
            self.assertEqual(session.current, third)
            self.assertEqual(session.apply("undo"), f"undid {second.name} → weird")
            self.assertEqual(session.current, second)
            self.assertEqual(session.apply("undo"), f"undid {first.name} → Dancing")
            self.assertEqual(session.current, first)
            self.assertEqual(session.apply("undo"), "nothing to undo")

        self.assertEqual(session.remaining, 4)

    def test_undoing_everything_rewinds_the_queue_to_its_original_order(self):
        session = self._session(count=5)
        with patch("backfill.session.record_action"), \
             patch("backfill.session.sidecar_snapshot", return_value=None), \
             patch("backfill.session.restore_sidecar"):
            original = []
            while session.current is not None:
                original.append(session.current)
                session.apply("dance")

            for _ in original:
                session.apply("undo")

            rewound = []
            while session.current is not None:
                rewound.append(session.current)
                session.apply("dance")

        self.assertEqual(rewound, original)


class TestSame(unittest.TestCase):
    def _session(self, count=3, worker=None):
        videos = [Path(f"clip{i}.mp4") for i in range(count)]
        queue = BackfillQueue(videos, rng=random.Random(0))
        return BackfillSession(queue, worker or ImmediateWorker())

    def test_same_records_the_last_action_against_the_clip_on_screen(self):
        session = self._session()
        first = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.sidecar_snapshot"):
            session.apply("pov delta")
            second = session.current
            note = session.apply("same")

        record.assert_any_call(second, "Pov Delta")
        self.assertEqual(note, f"{second.name} → Pov Delta")
        self.assertNotEqual(second, first)

    def test_same_before_any_action_repeats_nothing(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action") as record:
            note = session.apply("same")

        record.assert_not_called()
        self.assertEqual(note, "nothing to repeat")
        self.assertEqual(session.current, clip)
        self.assertEqual(session.remaining, 3)

    def test_same_reaches_past_a_skip_to_the_last_action(self):
        session = self._session()

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.sidecar_snapshot"):
            session.apply("dance")
            skipped = session.current
            session.apply("skip")
            after_skip = session.current
            note = session.apply("same")

        record.assert_any_call(after_skip, "Dancing")
        self.assertEqual(note, f"{after_skip.name} → Dancing")
        self.assertNotEqual(after_skip, skipped)

    def test_undoing_a_same_puts_the_clip_back(self):
        session = self._session()

        with patch("backfill.session.record_action"), \
             patch("backfill.session.sidecar_snapshot", return_value=None), \
             patch("backfill.session.restore_sidecar"):
            session.apply("dance")
            same_clip = session.current
            session.apply("same")
            note = session.apply("undo")

        self.assertEqual(note, f"undid {same_clip.name} → Dancing")
        self.assertEqual(session.current, same_clip)
        self.assertEqual(session.remaining, 2)

    def test_same_after_undoing_the_only_action_repeats_nothing(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.sidecar_snapshot", return_value=None), \
             patch("backfill.session.restore_sidecar"):
            session.apply("dance")
            session.apply("undo")
            self.assertEqual(session.current, clip)
            record.reset_mock()
            note = session.apply("same")

        record.assert_not_called()
        self.assertEqual(note, "nothing to repeat")
        self.assertEqual(session.current, clip)

    def test_consecutive_sames_keep_labelling_and_advancing(self):
        session = self._session(count=4)

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.sidecar_snapshot"):
            session.apply("gamma")
            session.apply("same")
            session.apply("same")

        actions = [call.args[1] for call in record.call_args_list]
        self.assertEqual(actions, ["Gamma", "Gamma", "Gamma"])
        self.assertEqual(session.remaining, 1)

    def test_same_after_the_last_clip_does_nothing(self):
        session = self._session(count=1)

        with patch("backfill.session.record_action"), patch("backfill.session.sidecar_snapshot"):
            session.apply("dance")
            note = session.apply("same")

        self.assertIsNone(note)
        self.assertIsNone(session.current)


class TestUndoAgainstRealFiles(unittest.TestCase):
    """The two reversals that actually touch disk, driven end to end."""

    def _tree(self, root):
        ai = root / "AI"
        upscaled = ai / "2_outbox" / "upscaled_by_orientation"
        video = upscaled / "portrait" / "provider2" / "a_topaz.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"video")
        return ai, upscaled, root / "metadata", root / "kinda_weird", video

    def _session(self, video):
        return BackfillSession(BackfillQueue([video]), ImmediateWorker())

    def test_undoing_an_act_deletes_the_sidecar_it_wrote(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata, weird, video = self._tree(root)

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata, WEIRD_DIR=weird):
                session = self._session(video)
                session.apply("pov delta")
                self.assertTrue(sidecar_path(video).is_file())

                session.apply("undo")

                self.assertFalse(sidecar_path(video).exists())
                self.assertEqual(session.current, video)

    def test_undoing_an_act_keeps_metadata_the_clip_already_had(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata, weird, video = self._tree(root)

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata, WEIRD_DIR=weird):
                path = sidecar_path(video)
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({"video": {"prompt": "a prompt"}}), encoding="utf-8")

                session = self._session(video)
                session.apply("dance")
                session.apply("undo")

                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8")), {"video": {"prompt": "a prompt"}}
                )

    def test_undoing_a_discard_brings_the_file_back(self):
        with workspace_temp_dir() as root:
            ai, upscaled, metadata, weird, video = self._tree(root)

            with override_config(VIDEO_LIBRARY_DIR=root, AI_DIR=ai, OUT_UPSCALED_DIR=upscaled, METADATA_DIR=metadata, WEIRD_DIR=weird):
                session = self._session(video)
                session.apply("weird")
                self.assertFalse(video.exists())
                self.assertTrue((weird / video.name).is_file())

                session.apply("undo")

                self.assertTrue(video.is_file())
                self.assertEqual(video.read_bytes(), b"video")
                self.assertEqual(list(weird.iterdir()), [])
                self.assertEqual(session.current, video)


if __name__ == "__main__":
    unittest.main()
