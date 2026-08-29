from unittest.mock import patch

import check_duplicate_sizes
from tests.temp_helpers import override_config, workspace_temp_dir


class TestDuplicateSizes:
    def test_run_is_ok_when_all_files_have_unique_sizes(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (sorted_dir / "sourceB" / "portrait").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (sorted_dir / "sourceB" / "portrait" / "clip-b.mp4").write_bytes(b"bb")

            with override_config(NON_AI_DIR=sorted_dir):
                result = check_duplicate_sizes.run(show_popup=False)

            assert result.ok
            assert result.scanned_count == 2
            assert result.duplicate_groups == {}

    def test_run_reports_exact_size_duplicates_and_can_show_popup(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (sorted_dir / "sourceB" / "portrait").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"same-size")
            (sorted_dir / "sourceB" / "portrait" / "clip-b.mp4").write_bytes(b"same-size")
            (sorted_dir / "sourceB" / "portrait" / "clip-c.mp4").write_bytes(b"different-size")

            with override_config(NON_AI_DIR=sorted_dir), \
                 patch("check_duplicate_sizes.show_error_window") as show_error_window:
                result = check_duplicate_sizes.run(show_popup=True)

            assert not result.ok
            assert result.scanned_count == 3
            assert len(result.duplicate_groups) == 1
            assert next(iter(result.duplicate_groups.values())) == [
                "sourceA\\landscape\\clip-a.mp4",
                "sourceB\\portrait\\clip-b.mp4",
            ]
            show_error_window.assert_called_once()

    def test_zero_byte_files_are_not_duplicates_of_each_other(self):
        """A crashed download leaves empty files; two of them share a size for
        no reason at all, and must not fail the run as a duplicate pair."""
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"")
            (sorted_dir / "sourceA" / "landscape" / "clip-b.mp4").write_bytes(b"")

            with override_config(NON_AI_DIR=sorted_dir):
                result = check_duplicate_sizes.run(show_popup=False)

            assert result.ok
            assert result.scanned_count == 2
