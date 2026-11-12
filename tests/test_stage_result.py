from __future__ import annotations

import pytest

from check_correspondence import CorrespondenceResult
from check_duplicate_sizes import DuplicateSizesResult
from tasks.bookmarks_sync import BookmarksSyncResult
from tasks.clip_scripts import ClipScriptsResult
from tasks.genau_deliver import GenauDeliverResult
from tasks.nonai_group import NonAiGroupResult
from tasks.nonai_titles import NonAiTitleResult
from tasks.nonai_upscale import NonAiUpscaleResult
from tasks.origenerator_commands import DowntimeResult
from tasks.prompt_scrape import PromptScrapeResult
from tasks.provenance_sweep import ProvenanceResult
from tasks.scene_scripts import SceneScriptsResult
from tasks.scripts_sync import ScriptsSyncResult
from tasks.sort import SortResult
from tasks.stray_files import StrayFilesResult
from tasks.unsent_videos import UnsentVideosResult
from tasks.upscale import UpscaleResult
from tasks.video_kinds import VideoKindsResult
from tasks.watch_weights import WatchWeightsResult

WENT_WELL = (True, False)
WANTS_AN_EYE = (True, True)
WENT_WRONG = (False, False)
WENT_WRONG_AND_WANTS_AN_EYE = (False, True)


@pytest.mark.parametrize(("result", "said"), [
    pytest.param(StrayFilesResult(renamed=2, rehomed_scripts=1), WENT_WELL,
                 id="stray files put right"),
    pytest.param(StrayFilesResult(reported=["example/notes one.txt"]), WANTS_AN_EYE,
                 id="a stray file only reported"),
    pytest.param(UnsentVideosResult(deleted=3), WENT_WELL, id="videos unsent"),
    pytest.param(UnsentVideosResult(deleted=1, failed=1), WENT_WRONG,
                 id="a copy of an unsent video that could not be deleted"),
    pytest.param(PromptScrapeResult(newly_scraped=4), WENT_WELL, id="prompts scraped"),
    pytest.param(PromptScrapeResult(newly_scraped=1, errors=1), WENT_WRONG,
                 id="a prompt scrape that errored"),

    pytest.param(SortResult(moved=5), WENT_WELL, id="the inbox sorted"),
    pytest.param(DowntimeResult(did="took notes on the collection"), WENT_WELL,
                 id="origenerator's downtime work started"),
    pytest.param(DowntimeResult(failed=True), WENT_WRONG,
                 id="origenerator's downtime command unanswered"),
    pytest.param(UpscaleResult(processed=2), WENT_WELL, id="videos upscaled"),
    pytest.param(UpscaleResult(processed=1, deferred_low_disk=True, pending_after_run=2),
                 WANTS_AN_EYE, id="an upscale held back by low disk"),
    pytest.param(UpscaleResult(failed=1, deferred_low_disk=True), WENT_WRONG_AND_WANTS_AN_EYE,
                 id="an upscale that failed a video and was held back"),
    pytest.param(GenauDeliverResult(delivered=2), WENT_WELL, id="flicks delivered"),
    pytest.param(GenauDeliverResult(failed=1), WENT_WRONG, id="a flick that could not be delivered"),
    pytest.param(NonAiUpscaleResult(in_flight="example/scene one.mp4"), WENT_WELL,
                 id="a non-AI encode under way"),
    pytest.param(NonAiUpscaleResult(deferred_low_disk=True), WANTS_AN_EYE,
                 id="a non-AI encode held back by low disk"),
    pytest.param(NonAiUpscaleResult(unreachable_archive="Q:/example archive"), WANTS_AN_EYE,
                 id="a finished non-AI encode waiting for the archive"),
    pytest.param(NonAiUpscaleResult(failed="example/scene one.mp4", deferred_low_disk=True),
                 WENT_WRONG_AND_WANTS_AN_EYE, id="a non-AI encode that died while held back"),
    pytest.param(CorrespondenceResult(sorted_count=2, upscale_count=2), WENT_WELL,
                 id="the sorted and upscaled videos correspond"),
    pytest.param(CorrespondenceResult(sorted_count=2, upscale_count=1,
                                      orphan_sorted=["example/video one.mp4"]), WENT_WRONG,
                 id="a sorted video with no upscale"),
    pytest.param(WatchWeightsResult(stamped=3), WENT_WELL, id="watching summed"),
    pytest.param(WatchWeightsResult(write_errors=1), WENT_WRONG, id="a sidecar that could not be written"),
    pytest.param(WatchWeightsResult(gallery_untold=True), WENT_WRONG,
                 id="origenerator's gallery not told"),
    pytest.param(BookmarksSyncResult(synced=2), WENT_WELL, id="favorites bookmarked"),
    pytest.param(BookmarksSyncResult(profile_missing=True), WENT_WRONG, id="no chrome profile"),
    pytest.param(BookmarksSyncResult(write_error="the bookmarks file is held"), WENT_WRONG,
                 id="the bookmarks could not be written"),
    pytest.param(ClipScriptsResult(written=1), WENT_WELL, id="clip scripts cut"),
    pytest.param(SceneScriptsResult(written=1), WENT_WELL, id="scene scripts written"),
    pytest.param(ScriptsSyncResult(moved=2), WENT_WELL, id="scripts moved into place"),
    pytest.param(ScriptsSyncResult(not_checked=3, unreachable=["Q:/example archive"]), WANTS_AN_EYE,
                 id="scripts left unchecked while a folder cannot be reached"),
    pytest.param(ScriptsSyncResult(unmatched=1, not_checked=3), WENT_WRONG_AND_WANTS_AN_EYE,
                 id="a script that matches no video"),
    pytest.param(NonAiGroupResult(grouped=2), WENT_WELL, id="version families recorded"),
    pytest.param(NonAiTitleResult(titled=2), WENT_WELL, id="titles recorded"),
    pytest.param(VideoKindsResult(recorded=2), WENT_WELL, id="video kinds recorded"),
    pytest.param(ProvenanceResult(looked_up=2), WENT_WELL, id="provenance recorded"),
    pytest.param(DuplicateSizesResult(scanned_count=4), WENT_WELL, id="no duplicate sizes"),
    pytest.param(DuplicateSizesResult(scanned_count=4,
                                      duplicate_groups={10: ["a/one.mp4", "b/two.mp4"]}),
                 WENT_WRONG, id="two videos the same size"),
])
def test_each_stage_says_in_the_same_two_words_whether_it_went_wrong_and_whether_it_wants_an_eye(
        result, said):
    assert (result.ok, result.needs_an_eye) == said
