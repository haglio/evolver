import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import config
import evolver
from tests.temp_helpers import workspace_temp_dir


class TestEvolverMain(unittest.TestCase):
    @patch("evolver._should_skip_upscale_due_to_cpu", return_value=False)
    @patch("evolver.upscale.has_pending_work", return_value=False)
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.scripts_sync.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_skips_upscale_when_no_pending_work(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        scripts_sync_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
        has_pending_work,
        should_skip_cpu,
    ):
        sort_run.return_value = Mock(moved=0, moved_files=[])
        purge_run.return_value = Mock(missing_sorted=[])
        scripts_sync_run.return_value = Mock(ok=True)
        duplicate_sizes_run.return_value = Mock(ok=True)
        correspondence_run.return_value = Mock(ok=True)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 0)
        purge_run.assert_called_once_with()
        scripts_sync_run.assert_called_once_with(show_popup=True)
        upscale_run.assert_not_called()
        duplicate_sizes_run.assert_called_once_with(show_popup=True)
        correspondence_run.assert_called_once_with(show_popup=True)

    @patch("evolver._should_skip_upscale_due_to_cpu", return_value=False)
    @patch("evolver.upscale.has_pending_work", return_value=True)
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.scripts_sync.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_exits_nonzero_on_correspondence_failure(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        scripts_sync_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
        has_pending_work,
        should_skip_cpu,
    ):
        sort_run.return_value = Mock(moved=1, moved_files=["new-file"])
        purge_run.return_value = Mock(missing_sorted=[])
        scripts_sync_run.return_value = Mock(ok=True)
        upscale_run.return_value = Mock(failed=0, deferred_low_disk=False)
        duplicate_sizes_run.return_value = Mock(ok=True)
        correspondence_run.return_value = Mock(ok=False)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 1)
        purge_run.assert_called_once_with()
        scripts_sync_run.assert_called_once_with(show_popup=True)
        upscale_run.assert_called_once_with(priority_files=["new-file"], max_items=evolver.config.UPSCALE_BATCH_LIMIT)
        duplicate_sizes_run.assert_called_once_with(show_popup=True)
        correspondence_run.assert_called_once_with(show_popup=True)

    @patch("evolver._should_skip_upscale_due_to_cpu", return_value=False)
    @patch("evolver.upscale.has_pending_work", return_value=False)
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.scripts_sync.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_exits_nonzero_on_duplicate_size_failure(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        scripts_sync_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
        has_pending_work,
        should_skip_cpu,
    ):
        sort_run.return_value = Mock(moved=0, moved_files=[])
        purge_run.return_value = Mock(missing_sorted=[])
        scripts_sync_run.return_value = Mock(ok=True)
        duplicate_sizes_run.return_value = Mock(ok=False)
        correspondence_run.return_value = Mock(ok=True)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 1)
        purge_run.assert_called_once_with()
        scripts_sync_run.assert_called_once_with(show_popup=True)
        upscale_run.assert_not_called()
        duplicate_sizes_run.assert_called_once_with(show_popup=True)
        correspondence_run.assert_called_once_with(show_popup=True)

    @patch("evolver._should_skip_upscale_due_to_cpu", return_value=True)
    @patch("evolver.upscale.has_pending_work", return_value=True)
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.scripts_sync.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_skips_upscale_when_cpu_busy(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        scripts_sync_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
        has_pending_work,
        should_skip_cpu,
    ):
        sort_run.return_value = Mock(moved=1, moved_files=["new-file"])
        purge_run.return_value = Mock(missing_sorted=[])
        scripts_sync_run.return_value = Mock(ok=True)
        duplicate_sizes_run.return_value = Mock(ok=True)
        correspondence_run.return_value = Mock(ok=True)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 0)
        scripts_sync_run.assert_called_once_with(show_popup=True)
        upscale_run.assert_not_called()

    @patch("evolver._should_skip_upscale_due_to_cpu", return_value=False)
    @patch("evolver.upscale.has_pending_work", return_value=False)
    @patch("evolver.check_duplicate_sizes.run")
    @patch("evolver.check_correspondence.run")
    @patch("evolver.upscale.run")
    @patch("evolver.scripts_sync.run")
    @patch("evolver.purge_weird.run")
    @patch("evolver.sort.run")
    @patch("evolver.check_dependencies")
    @patch("evolver.setup_logging")
    def test_main_exits_nonzero_on_scripts_sync_failure(
        self,
        setup_logging,
        check_dependencies,
        sort_run,
        purge_run,
        scripts_sync_run,
        upscale_run,
        duplicate_sizes_run,
        correspondence_run,
        has_pending_work,
        should_skip_cpu,
    ):
        sort_run.return_value = Mock(moved=0, moved_files=[])
        purge_run.return_value = Mock(missing_sorted=[])
        scripts_sync_run.return_value = Mock(ok=False)
        duplicate_sizes_run.return_value = Mock(ok=True)
        correspondence_run.return_value = Mock(ok=True)

        with self.assertRaises(SystemExit) as exc:
            evolver.main()

        self.assertEqual(exc.exception.code, 1)
        scripts_sync_run.assert_called_once_with(show_popup=True)
        upscale_run.assert_not_called()

    def test_finish_regen_if_complete_simplifies_fun_time_config(self):
        with workspace_temp_dir() as root:
            old_outbox = root / "2_outbox"
            regen_outbox = root / "3_new_outbox"
            fun_time_config = root / "fun_time_config.json"
            marker = root / ".regen-complete"
            cleanup_note = root / "POST_REGEN_CLEANUP.md"

            (old_outbox / "upscaled_by_orientation").mkdir(parents=True)
            (regen_outbox / "upscaled_by_orientation" / "portrait" / "src").mkdir(parents=True)
            (regen_outbox / "upscaled_by_orientation" / "landscape" / "src").mkdir(parents=True)
            (regen_outbox / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.mp4").write_bytes(b"x")
            (regen_outbox / "upscaled_by_orientation" / "landscape" / "src" / "clip_topaz.mp4").write_bytes(b"x")
            fun_time_config.write_text(
                '{\n'
                '  "paths": {\n'
                '    "portrait_dirs": ["old", "new"],\n'
                '    "landscape_dirs": ["old", "new"]\n'
                "  }\n"
                "}\n",
                encoding="utf-8",
            )

            saved = {
                "OUTBOX_DIR": config.OUTBOX_DIR,
                "OUT_UPSCALED_DIR": config.OUT_UPSCALED_DIR,
                "REGEN_OUTBOX_DIR": config.REGEN_OUTBOX_DIR,
                "REGEN_OUT_UPSCALED_DIR": config.REGEN_OUT_UPSCALED_DIR,
                "REGEN_COMPLETE_MARKER": config.REGEN_COMPLETE_MARKER,
                "POST_REGEN_CLEANUP_NOTE": config.POST_REGEN_CLEANUP_NOTE,
                "FUN_TIME_CONFIG_FILE": config.FUN_TIME_CONFIG_FILE,
                "REGEN_ENABLED": config.REGEN_ENABLED,
                "AUTO_CUTOVER_ON_REGEN_COMPLETE": config.AUTO_CUTOVER_ON_REGEN_COMPLETE,
            }
            config.OUTBOX_DIR = old_outbox
            config.OUT_UPSCALED_DIR = old_outbox / "upscaled_by_orientation"
            config.REGEN_OUTBOX_DIR = regen_outbox
            config.REGEN_OUT_UPSCALED_DIR = regen_outbox / "upscaled_by_orientation"
            config.REGEN_COMPLETE_MARKER = marker
            config.POST_REGEN_CLEANUP_NOTE = cleanup_note
            config.FUN_TIME_CONFIG_FILE = fun_time_config
            config.REGEN_ENABLED = True
            config.AUTO_CUTOVER_ON_REGEN_COMPLETE = True
            try:
                with patch("evolver.show_info_window") as show_info_window:
                    done = evolver._finish_regen_if_complete(Mock(), Mock(ok=True))
                self.assertTrue(done)
                self.assertTrue(show_info_window.called)
                popup_message = show_info_window.call_args.args[1]
                self.assertIn("Manual review recommended", popup_message)
                self.assertIn("REGEN_ENABLED back to False", popup_message)
                self.assertTrue(marker.exists())
                self.assertTrue(cleanup_note.exists())
                self.assertTrue((old_outbox / "upscaled_by_orientation" / "portrait" / "src" / "clip_topaz.mp4").exists())
                updated = fun_time_config.read_text(encoding="utf-8")
                self.assertIn('"portrait_dirs": [', updated)
                self.assertIn('"landscape_dirs": [', updated)
                self.assertIn('2_outbox/upscaled_by_orientation/portrait', updated)
                self.assertIn('2_outbox/upscaled_by_orientation/landscape', updated)
                self.assertNotIn('"old", "new"', updated)
                note_text = cleanup_note.read_text(encoding="utf-8")
                self.assertIn("Post-Regen Cleanup", note_text)
                self.assertIn("REGEN_ENABLED back to False", note_text)
            finally:
                for key, value in saved.items():
                    setattr(config, key, value)


if __name__ == "__main__":
    unittest.main()
