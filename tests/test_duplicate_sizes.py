from __future__ import annotations

from pathlib import Path
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
                 patch("check_duplicate_sizes.show_error") as show_error:
                result = check_duplicate_sizes.run(show_popup=True)

            assert not result.ok
            assert result.scanned_count == 3
            assert len(result.duplicate_groups) == 1
            assert next(iter(result.duplicate_groups.values())) == [
                "sourceA\\landscape\\clip-a.mp4",
                "sourceB\\portrait\\clip-b.mp4",
            ]
            show_error.assert_called_once()

    def test_the_empty_files_a_crashed_download_leaves_are_not_duplicates_of_each_other(self):
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

    def test_a_duplicate_is_named_relative_to_the_same_folder_that_was_scanned(self):
        with workspace_temp_dir() as root:
            given = root / "given"
            (given / "examplebucket").mkdir(parents=True)
            (given / "examplebucket" / "clip two.mp4").write_bytes(b"same-size")
            (given / "examplebucket" / "clip three.mp4").write_bytes(b"same-size")

            with override_config(NON_AI_DIR=root):
                result = check_duplicate_sizes.run(show_popup=False, non_ai_dir=given)

            assert result.duplicate_groups == {
                9: [str(Path("examplebucket") / "clip three.mp4"), str(Path("examplebucket") / "clip two.mp4")]}


class TestMain:
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
