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

    def test_run_scans_the_folder_it_is_given(self):
        """The root scanned and the root paths are reported relative to are one
        thing, and it is an argument now. The ambient folder here holds a
        duplicate pair the given one does not."""
        with workspace_temp_dir() as root:
            given = root / "given"
            (given / "examplebucket").mkdir(parents=True)
            (given / "examplebucket" / "clip one.mp4").write_bytes(b"unique")

            ambient = root / "ambient"
            (ambient / "examplebucket").mkdir(parents=True)
            (ambient / "examplebucket" / "clip two.mp4").write_bytes(b"same-size")
            (ambient / "examplebucket" / "clip three.mp4").write_bytes(b"same-size")

            with override_config(NON_AI_DIR=ambient):
                result = check_duplicate_sizes.run(show_popup=False, non_ai_dir=given)

            assert result.ok
            assert result.scanned_count == 1


class TestMain:
    """The standalone entry point's report and exit code, previously untested
    (main() was the whole of the file's missing coverage)."""

    def test_a_clean_tree_reports_ok_and_exits_zero(self, capsys):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")

            with override_config(NON_AI_DIR=sorted_dir):
                exit_code = check_duplicate_sizes.main()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "[OK]" in out

    def test_a_duplicate_pair_is_named_and_exits_one(self, capsys):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"same-size")
            (sorted_dir / "sourceA" / "landscape" / "clip-b.mp4").write_bytes(b"same-size")

            with override_config(NON_AI_DIR=sorted_dir):
                exit_code = check_duplicate_sizes.main()

        out = capsys.readouterr().out
        assert exit_code == 1
        assert "[DUPLICATE] 1 exact-size duplicate group(s) found:" in out
        assert "clip-a.mp4" in out
        assert "clip-b.mp4" in out
        assert "[FAIL]" in out
