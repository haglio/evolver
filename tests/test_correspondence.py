from pathlib import Path
from unittest.mock import patch

import pytest

import check_correspondence
from tests.temp_helpers import override_config, workspace_temp_dir


class TestSortedToOutboxName:
    @pytest.mark.parametrize(
        ("sorted_file", "expected"),
        [
            (Path("clip.mp4"), "clip_topaz.mp4"),
            (Path("clip_apo8_gcg5.mp4"), "clip_apo8_gcg5_topaz.mp4"),
            (Path("a.mkv"), "a_topaz.mkv"),
        ],
    )
    def test_appends_topaz_before_extension(self, sorted_file, expected):
        assert check_correspondence.sorted_to_outbox_name(sorted_file) == expected


class TestCorrespondenceResult:
    def test_ok_requires_matching_counts_and_no_orphans(self):
        result = check_correspondence.CorrespondenceResult(sorted_count=5, outbox_count=5)
        assert result.ok

    def test_not_ok_on_count_mismatch(self):
        result = check_correspondence.CorrespondenceResult(sorted_count=5, outbox_count=3)
        assert not result.ok

    def test_not_ok_on_orphan_outbox(self):
        result = check_correspondence.CorrespondenceResult(
            sorted_count=1, outbox_count=1, orphan_outbox=["stray.mp4"],
        )
        assert not result.ok

    def test_not_ok_on_duplicates(self):
        result = check_correspondence.CorrespondenceResult(
            sorted_count=2, outbox_count=2, duplicates={"clip_topaz.mp4": ["a", "b"]},
        )
        assert not result.ok


class TestCorrespondence:
    def test_run_accepts_outbox_names_as_sorted_plus_topaz(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (sorted_dir / "sourceB" / "portrait").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "portrait" / "sourceB").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (sorted_dir / "sourceB" / "portrait" / "clip-b_apo8_gcg5.mp4").write_bytes(b"b")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a_topaz.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "portrait" / "sourceB" / "clip-b_apo8_gcg5_topaz.mp4").write_bytes(b"b")

            with override_config(SORTED_DIR=sorted_dir, OUTBOX_DIR=outbox_dir):
                result = check_correspondence.run(show_popup=False)

            assert result.ok
            assert result.sorted_count == 2
            assert result.outbox_count == 2

    def test_run_reports_mismatches_and_can_show_popup(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-b_topaz.mp4").write_bytes(b"b")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-b_topaz_cfr.mp4").write_bytes(b"c")

            with override_config(SORTED_DIR=sorted_dir, OUTBOX_DIR=outbox_dir):
                with patch("check_correspondence.show_error_window") as show_error_window:
                    result = check_correspondence.run(show_popup=True)

            assert not result.ok
            assert result.sorted_count == 1
            assert result.outbox_count == 2
            assert len(result.orphan_outbox) == 2
            assert len(result.orphan_sorted) == 1
            assert result.duplicates == {}
            show_error_window.assert_called_once()

    def test_run_detects_two_outbox_files_sharing_a_basename(self):
        """The duplicate map is a named failure mode of the stage -- it fails
        the run and names both paths in the popup -- yet the detection ran under
        no test at all: relaxing `len(paths) > 1` to `> 99` changed nothing
        (audit probe P24). Two orientations of one clip both upscaled produce
        exactly this: same basename, two outbox folders, every file matched."""
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"

            for orient in ("landscape", "portrait"):
                (sorted_dir / "sourceA" / orient).mkdir(parents=True)
                (outbox_dir / "upscaled_by_orientation" / orient / "sourceA").mkdir(parents=True)
                (sorted_dir / "sourceA" / orient / "clip-a.mp4").write_bytes(b"a")
                (outbox_dir / "upscaled_by_orientation" / orient / "sourceA" / "clip-a_topaz.mp4").write_bytes(b"a")

            with override_config(SORTED_DIR=sorted_dir, OUTBOX_DIR=outbox_dir):
                result = check_correspondence.run(show_popup=False)

            assert not result.ok
            assert list(result.duplicates) == ["clip-a_topaz.mp4"]
            paths = result.duplicates["clip-a_topaz.mp4"]
            assert len(paths) == 2
            assert any("landscape" in p for p in paths)
            assert any("portrait" in p for p in paths)
            # the duplicate pair is fully matched, so it is only the
            # duplication that fails the run
            assert result.orphan_outbox == []
            assert result.orphan_sorted == []

    def test_run_ignores_partial_outbox_files(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"

            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)

            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a_topaz.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a.partial.deadbeef.mp4").write_bytes(b"partial")

            with override_config(SORTED_DIR=sorted_dir, OUTBOX_DIR=outbox_dir):
                result = check_correspondence.run(show_popup=False)

            assert result.ok
            assert result.sorted_count == 1
            assert result.outbox_count == 1


class TestMain:
    """The standalone entry point: the exit code is the contract a shell or a
    scheduled task reads, and the printed report is how the check is run by
    hand. Neither had a single test (66% file coverage, main() all missing)."""

    def test_a_clean_tree_reports_ok_and_exits_zero(self, capsys):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"
            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)
            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-a_topaz.mp4").write_bytes(b"a")

            with override_config(SORTED_DIR=sorted_dir, OUTBOX_DIR=outbox_dir):
                exit_code = check_correspondence.main()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "[OK] Counts match: 1 files each" in out
        assert "perfect 1-to-1 correspondence" in out

    def test_a_mismatched_tree_names_the_orphans_and_exits_one(self, capsys):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            outbox_dir = root / "outbox"
            (sorted_dir / "sourceA" / "landscape").mkdir(parents=True)
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA").mkdir(parents=True)
            (sorted_dir / "sourceA" / "landscape" / "clip-a.mp4").write_bytes(b"a")
            (outbox_dir / "upscaled_by_orientation" / "landscape" / "sourceA" / "clip-b_topaz.mp4").write_bytes(b"b")

            with override_config(SORTED_DIR=sorted_dir, OUTBOX_DIR=outbox_dir):
                exit_code = check_correspondence.main()

        out = capsys.readouterr().out
        assert exit_code == 1
        assert "[MISMATCH]" not in out  # counts match at 1 vs 1
        assert "[ORPHAN-OUTBOX]" in out
        assert "clip-b_topaz.mp4" in out
        assert "[ORPHAN-SORTED]" in out
        assert "[FAIL]" in out
