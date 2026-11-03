from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PyQt6.QtCore import QMimeData

from gui import branch_session, run_record
from gui.queue_window import VIDEO_MIME, dropped_video
from gui.status_symbols import status_icon
from tasks import nonai_request, prompt_scrape
from tests.temp_helpers import override_config
from util import media_files, nonai_library, script_library, system_resources
from util.html_query import parse_document


class TestWhenAPreviewHandsTheWorkBack:
    def test_the_hour_is_read_on_a_twelve_hour_clock_without_a_leading_zero(self):
        assert branch_session.until(datetime(2026, 1, 1, 8, 30, tzinfo=UTC)) == "9:30 AM"
        assert branch_session.until(datetime(2026, 1, 1, 12, 15, tzinfo=UTC)) == "1:15 PM"


class TestRelaunchingAPreview:
    def test_a_preview_is_started_again_through_its_own_launcher(self):
        with override_config(BRANCH_SESSION=True, PROJECT_DIR=Path("checkout")):
            command = branch_session.relaunch_command()

        assert command == f'wscript.exe "{Path("checkout") / "launch_preview_branch.vbs"}"'


class TestADragCarryingNoVideo:
    def test_it_reads_as_an_empty_name(self):
        assert dropped_video(QMimeData()) == ""

    def test_a_dragged_video_is_read_back_by_name(self):
        carried = QMimeData()
        carried.setData(VIDEO_MIME, b"lagoon/b.mp4")

        assert dropped_video(carried) == "lagoon/b.mp4"


class TestAStatusWithNoMark:
    def test_it_gives_an_icon_with_nothing_drawn(self):
        assert status_icon("never heard of it").isNull()


class TestAFileThatCannotBeRead:
    def test_its_size_reads_as_zero(self, tmp_path):
        assert media_files.file_size(tmp_path / "gone.mp4") == 0

    def test_a_file_reads_as_its_size_in_bytes(self, tmp_path):
        video = tmp_path / "a.mp4"
        video.write_bytes(b"12345")

        assert media_files.file_size(video) == 5


class TestAFolderThatCannotBeListed:
    def test_it_does_not_hold_the_stages(self, tmp_path):
        assert not nonai_library.holds_stages(tmp_path / "gone")


class TestWritingARun:
    def test_a_result_that_is_not_a_dataclass_keeps_its_public_fields_only(self):
        class Result:
            def __init__(self):
                self.moved = 3
                self._scratch = "x"

        assert run_record.result_to_dict(Result()) == {"moved": 3}

    def test_a_dataclass_result_keeps_every_field(self):
        @dataclass
        class Result:
            moved: int = 3
            _scratch: str = "x"

        assert run_record.result_to_dict(Result()) == {"moved": 3, "_scratch": "x"}


class TestAnEncodeThatHasAlreadyEnded:
    def test_asking_for_another_video_leaves_it_alone_to_be_concluded(self):
        job = {"pid": None, "source": "lagoon/0 unsorted/a.mp4"}

        assert nonai_request.make_way_for("lagoon/0 unsorted/b.mp4", job, files=None) == (job, "")


class TestStampingAScript:
    def test_the_script_given_is_not_written_on(self):
        script = {"actions": [], "metadata": {"title": "scene one"}}

        script_library.stamped(script, "trim")

        assert script == {"actions": [], "metadata": {"title": "scene one"}}

    def test_a_script_with_no_metadata_gets_the_stamp_alone(self):
        stamped = script_library.stamped({"actions": []}, "trim")

        assert list(stamped["metadata"]["provenance"]) == ["trim"]


class TestMeasuringTheCpu:
    def test_a_clock_that_did_not_move_reads_as_idle(self, monkeypatch):
        monkeypatch.setattr(system_resources, "_get_system_times", lambda: (10, 20, 30))

        assert system_resources.measure_cpu_busy_percent(0.0) == 0.0


class TestTheNegativePromptOnAPage:
    def test_a_positive_prompt_that_mentions_the_label_is_not_taken_for_it(self):
        panel = parse_document(
            '<div><div class="max-h-80">no negative prompt here</div>'
            '<span>Negative prompt</span><div class="max-h-80">blurry</div></div>')

        assert prompt_scrape._extract_negative_prompt_text(panel.children[0]) == "blurry"


class TestTheRecordAPageEmbeds:
    def test_the_first_mention_of_the_id_that_has_a_prompt_is_the_record(self):
        padding = " " * 12_000
        html = '{"id":"abc","prompt":"first"}' + padding + '{"id":"abc","prompt":"second"}'

        assert prompt_scrape._extract_provider_embedded_metadata(html, "abc").prompt == "first"

    def test_a_prompt_far_enough_away_belongs_to_the_next_item_and_is_not_read(self):
        html = '{"id":"abc"}' + " " * 6_000 + '{"id":"next","prompt":"not mine"}'

        assert prompt_scrape._extract_provider_embedded_metadata(html, "abc").prompt == ""
