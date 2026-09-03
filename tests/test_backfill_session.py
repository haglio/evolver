import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backfill.queue import BackfillQueue
from backfill import session
from backfill.session import BackfillSession
from tests.temp_helpers import library_tree
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
        queue = BackfillQueue(videos)
        return BackfillSession(queue, worker or ImmediateWorker())

    def test_a_control_the_session_does_not_dispatch_moves_no_file(self):
        """The four controls are dispatched by name. A fifth added to the
        vocabulary and not here has to do nothing: the fallback used to be the
        discard path, which moves the clip on screen into the weird folder."""
        session = self._session()
        clip = session.current

        with patch.dict("backfill.session.CONTROLS", {"reticulate": "reticulate"}):
            note = session.apply("reticulate")

        self.assertIsNone(note)
        self.assertEqual(session.current, clip)

    def test_an_act_records_the_action_against_the_clip_on_screen(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.sidecar_snapshot"):
            note = session.apply("side beta")

        record.assert_called_once_with(clip, "Side Beta")
        self.assertEqual(note, f"{clip.name} → Side Beta")

    def test_an_act_retires_the_clip(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action"), patch("backfill.session.sidecar_snapshot"):
            session.apply("side dance")

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
            session.apply("side dance")
            note = session.apply("side dance")

        self.assertIsNone(note)
        self.assertIsNone(session.current)

    def test_the_clip_advances_before_the_file_work_runs(self):
        """The session's headline promise, observed at the dispatch itself.

        A worker that merely held every task could not see the ordering:
        swapping take_effect and submit in _commit left the whole suite green
        (audit probe 19), because record_action was unrun under either order.
        This worker looks at the queue the moment submit is called, so the
        order of the two statements is the thing under test.
        """
        class QueueWatchingWorker:
            def __init__(self):
                self.pending = []
                self.on_screen_at_submit = []
                self.session = None

            def submit(self, task):
                self.on_screen_at_submit.append(self.session.current)
                self.pending.append(task)

            def drain(self):
                while self.pending:
                    self.pending.pop(0)()

        worker = QueueWatchingWorker()
        session = self._session(worker=worker)
        worker.session = session
        clip = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.sidecar_snapshot"):
            session.apply("side dance")

            record.assert_not_called()
            self.assertNotEqual(session.current, clip)
            # the clip had already left the screen when its work was dispatched
            self.assertEqual(worker.on_screen_at_submit, [session.current])

            worker.drain()
            record.assert_called_once_with(clip, "Side Dancing")


class TestUndo(unittest.TestCase):
    def _session(self, count=3, worker=None):
        videos = [Path(f"clip{i}.mp4") for i in range(count)]
        queue = BackfillQueue(videos)
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
            session.apply("side dance")
            note = session.apply("undo")

        restore.assert_called_once_with(clip, None)
        self.assertEqual(note, f"undid {clip.name} → Side Dancing")
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

    def test_undoing_a_discard_whose_move_failed_reclaims_nothing(self):
        """A discard can die on a clip the player never releases; its file work
        raised and nothing landed in the weird folder. Undo must not then try
        to reclaim from where nothing is -- the None-guard in roll_back was
        deletable with the suite green (audit probe 18)."""
        class SwallowingWorker(ImmediateWorker):
            """SerialWorker's real contract: a failing task never reaches the
            caller."""

            def submit(self, task):
                try:
                    task()
                except Exception:
                    pass

        session = self._session(worker=SwallowingWorker())
        clip = session.current

        with patch("backfill.session.discard_as_weird",
                   side_effect=PermissionError(32, "still playing")), \
             patch("backfill.session.reclaim_from_weird") as reclaim:
            session.apply("weird")
            note = session.apply("undo")

        reclaim.assert_not_called()
        self.assertEqual(note, f"undid {clip.name} → weird")
        self.assertEqual(session.current, clip)

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
            session.apply("side dance")
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
            session.apply("side dance")
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
            session.apply("side dance")
            second = session.current
            session.apply("weird")
            third = session.current
            session.apply("skip")

            self.assertEqual(session.apply("undo"), f"undid {third.name} → skipped")
            self.assertEqual(session.current, third)
            self.assertEqual(session.apply("undo"), f"undid {second.name} → weird")
            self.assertEqual(session.current, second)
            self.assertEqual(session.apply("undo"), f"undid {first.name} → Side Dancing")
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
                session.apply("side dance")

            for _ in original:
                session.apply("undo")

            rewound = []
            while session.current is not None:
                rewound.append(session.current)
                session.apply("side dance")

        self.assertEqual(rewound, original)


class TestSame(unittest.TestCase):
    """"Same" against the real decisions module: the sidecars are the record.

    These eight tests used to patch record_action and read the mock's calls --
    part of the 46 patches this file held on backfill.decisions, which is the
    unit's own cheap collaborator over the filesystem, not a boundary
    (evolver/util_backfill/tests/004). What "same" did is now read where Fun
    Time and genau would read it: the sidecar JSON.
    """

    def _session(self, lib, count=3):
        videos = [lib.video(name=f"clip{i}_topaz.mp4") for i in range(count)]
        return BackfillSession(BackfillQueue(videos), ImmediateWorker())

    def _recorded_action(self, clip):
        path = sidecar_path(clip)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["video"].get("action")

    def test_same_records_the_last_action_against_the_clip_on_screen(self):
        with library_tree() as lib:
            session = self._session(lib)
            first = session.current

            session.apply("pov zeta")
            second = session.current
            note = session.apply("same")

            self.assertEqual(self._recorded_action(second), "POV Zeta")
            self.assertEqual(note, f"{second.name} → POV Zeta")
            self.assertNotEqual(second, first)

    def test_same_repeats_the_most_recent_act_not_the_first(self):
        """No other test ever speaks two DIFFERENT acts before "same", so the
        direction of _last_action's walk was invisible: reversing it -- making
        "same" repeat the session's first act -- left all 149 tests green
        (audit probe 9). In use that writes the wrong action into every clip
        of a run, and fun_time and genau read the sidecar it lands in."""
        with library_tree() as lib:
            session = self._session(lib, count=4)

            session.apply("side dance")
            session.apply("pov zeta")
            third = session.current
            note = session.apply("same")

            self.assertEqual(self._recorded_action(third), "POV Zeta")
            self.assertEqual(note, f"{third.name} → POV Zeta")

    def test_same_before_any_action_repeats_nothing(self):
        with library_tree() as lib:
            session = self._session(lib)
            clip = session.current

            note = session.apply("same")

            self.assertIsNone(self._recorded_action(clip))
            self.assertEqual(note, "nothing to repeat")
            self.assertEqual(session.current, clip)
            self.assertEqual(session.remaining, 3)

    def test_same_reaches_past_a_skip_to_the_last_action(self):
        with library_tree() as lib:
            session = self._session(lib)

            session.apply("side dance")
            skipped = session.current
            session.apply("skip")
            after_skip = session.current
            note = session.apply("same")

            self.assertEqual(self._recorded_action(after_skip), "Side Dancing")
            self.assertEqual(note, f"{after_skip.name} → Side Dancing")
            self.assertNotEqual(after_skip, skipped)
            self.assertIsNone(self._recorded_action(skipped))

    def test_undoing_a_same_puts_the_clip_back(self):
        with library_tree() as lib:
            session = self._session(lib)

            session.apply("side dance")
            same_clip = session.current
            session.apply("same")
            note = session.apply("undo")

            self.assertIsNone(self._recorded_action(same_clip))
            self.assertEqual(note, f"undid {same_clip.name} → Side Dancing")
            self.assertEqual(session.current, same_clip)
            self.assertEqual(session.remaining, 2)

    def test_same_after_undoing_the_only_action_repeats_nothing(self):
        with library_tree() as lib:
            session = self._session(lib)
            clip = session.current

            session.apply("side dance")
            session.apply("undo")
            self.assertEqual(session.current, clip)
            note = session.apply("same")

            self.assertIsNone(self._recorded_action(clip))
            self.assertEqual(note, "nothing to repeat")
            self.assertEqual(session.current, clip)

    def test_consecutive_sames_keep_labelling_and_advancing(self):
        with library_tree() as lib:
            session = self._session(lib, count=4)
            clips = [session.current]

            session.apply("side beta")
            clips.append(session.current)
            session.apply("same")
            clips.append(session.current)
            session.apply("same")

            for clip in clips:
                self.assertEqual(self._recorded_action(clip), "Side Beta")
            self.assertEqual(session.remaining, 1)

    def test_same_after_the_last_clip_does_nothing(self):
        with library_tree() as lib:
            session = self._session(lib, count=1)

            session.apply("side dance")
            note = session.apply("same")

            self.assertIsNone(note)
            self.assertIsNone(session.current)


class TestUndoAgainstRealFiles(unittest.TestCase):
    """The two reversals that actually touch disk, driven end to end."""

    def _session(self, video):
        return BackfillSession(BackfillQueue([video]), ImmediateWorker())

    def test_undoing_an_act_deletes_the_sidecar_it_wrote(self):
        with library_tree() as lib:
            video = lib.video()
            session = self._session(video)
            session.apply("pov zeta")
            self.assertTrue(sidecar_path(video).is_file())

            session.apply("undo")

            self.assertFalse(sidecar_path(video).exists())
            self.assertEqual(session.current, video)

    def test_undoing_an_act_keeps_metadata_the_clip_already_had(self):
        with library_tree() as lib:
            video = lib.video()
            path = sidecar_path(video)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"video": {"prompt": "a prompt"}}), encoding="utf-8")

            session = self._session(video)
            session.apply("side dance")
            session.apply("undo")

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), {"video": {"prompt": "a prompt"}}
            )

    def test_undoing_a_discard_brings_the_file_back(self):
        with library_tree() as lib:
            video = lib.video()
            session = self._session(video)
            session.apply("weird")
            self.assertFalse(video.exists())
            self.assertTrue((lib.weird / video.name).is_file())

            session.apply("undo")

            self.assertTrue(video.is_file())
            self.assertEqual(video.read_bytes(), b"video")
            self.assertEqual(list(lib.weird.iterdir()), [])
            self.assertEqual(session.current, video)


class TestTheStepContract(unittest.TestCase):
    """The three decision kinds are related only by carrying the same five names.

    The module's docstring said every decision is a :class:`_Step` while no such
    thing existed anywhere in the repo, so the cross-reference pointed at
    nothing and a reader went looking for a class that was never written. It is
    a Protocol now, and this is what says the three still answer to it.
    """

    def test_every_decision_kind_carries_all_five_members(self):
        for kind in (session._Labelled, session._Discarded, session._Deferred):
            with self.subTest(kind=kind.__name__):
                for member in ("note", "take_effect", "put_back", "commit", "roll_back"):
                    self.assertTrue(hasattr(kind, member), member)

    def test_the_protocol_names_exactly_those_five(self):
        """So a sixth member added to one kind and not the others cannot quietly
        become something the session calls."""
        declared = {
            name for name in vars(session._Step)
            if not name.startswith("_")
        }
        self.assertEqual(
            declared, {"note", "take_effect", "put_back", "commit", "roll_back"}
        )


if __name__ == "__main__":
    unittest.main()
