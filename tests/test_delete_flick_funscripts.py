from __future__ import annotations

import json
from pathlib import Path

import pytest
from app_support import funscript

from tests.gallery_fakes import a_gallery_of, kept_at
from tests.temp_helpers import LaneLibrary, touch_video
from tools import delete_flick_funscripts
from util import origenerator_gallery, script_library

GENAU_SOURCE = "example-loop-clips"
BY_GOBLINSCRIPT = {"metadata": {"creator": "GoblinScript v0.6.0"}, "actions": []}
BY_A_PERSON = {"actions": []}


@pytest.fixture
def library(tmp_path):
    lanes = LaneLibrary(tmp_path)
    with lanes.config(genau_source=GENAU_SOURCE, ORIGENERATOR_SCRIPTS_DIR=tmp_path / "origenerator scripts",
                      ORIGENERATOR_PROJECT_DIR=tmp_path / "no origenerator here",
                      NONAI_RETIRED_ROOT=tmp_path / "archive"):
        yield lanes


def _script_for(library: LaneLibrary, video: Path, written: dict, *, generated: bool = False) -> Path:
    script = (library.scripts / video.relative_to(library.library)).with_suffix(".funscript")
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(json.dumps(written), encoding="utf-8")
    if generated:
        script_library.mark_generated(script)
    return script


def _run(*arguments: str, capsys) -> list[str]:
    assert delete_flick_funscripts.main(list(arguments)) == 0
    return capsys.readouterr().out.splitlines()


def _one_flick_of_each_kind_in_each_place(library: LaneLibrary) -> dict[str, Path]:
    flick = touch_video(library.genau_flicks / "2D" / "AI" / "loop one_topaz.mp4")
    in_trash = touch_video(library.genau_trash / "loop two_topaz.mp4")
    sorted_copy = touch_video(library.sorted_dir / GENAU_SOURCE / "portrait" / "loop three.mp4")
    in_inbox = touch_video(library.inbox / GENAU_SOURCE / "loop four.mp4")
    return {
        "goblinscript": _script_for(library, flick, BY_GOBLINSCRIPT),
        "no person": _script_for(library, in_trash, BY_A_PERSON, generated=True),
        "a person": _script_for(library, sorted_copy, BY_A_PERSON),
        "goblinscript in the inbox": _script_for(library, in_inbox, BY_GOBLINSCRIPT),
    }


def test_with_no_flag_it_counts_each_place_and_kind_and_deletes_nothing(library, capsys):
    scripts = _one_flick_of_each_kind_in_each_place(library)
    video = touch_video(library.sorted_dir / "example-source" / "portrait" / "video one.mp4")
    its_script = _script_for(library, video, BY_GOBLINSCRIPT)

    said = _run(capsys=capsys)

    assert said[1:10] == [
        "  Genau's folder: 1 made by GoblinScript, 0 written by no person, 0 written by a person",
        "  Genau's trash: 0 made by GoblinScript, 1 written by no person, 0 written by a person",
        "  `1_sorted`, Genau lane: 0 made by GoblinScript, 0 written by no person, 1 written by a person",
        "  `0_inbox`, Genau lane: 1 made by GoblinScript, 0 written by no person, 0 written by a person",
        "  Origenerator has not said which of its files are flicks yet: 0 looked at",
        "  Scripts folder, Genau lane, video gone: 0 made by GoblinScript, 0 written by no person, "
        "0 written by a person",
        "  `unmatched_scripts`: 0 made by GoblinScript, 0 written by no person, 0 written by a person",
        "  Non-AI archive: 0 made by GoblinScript, 0 written by no person, 0 written by a person",
        "  Total: 2 made by GoblinScript, 1 written by no person, 1 written by a person",
    ]
    assert all(script.is_file() for script in [*scripts.values(), its_script])


def test_it_names_no_file_of_the_library(library, capsys):
    _one_flick_of_each_kind_in_each_place(library)

    said = "\n".join(_run(capsys=capsys) + _run("--apply", capsys=capsys))

    assert ("loop" not in said, "example" not in said, str(library.library) not in said) == (True, True, True)


def test_apply_deletes_what_no_person_wrote_and_leaves_what_a_person_wrote(library, capsys):
    scripts = _one_flick_of_each_kind_in_each_place(library)

    said = _run("--apply", capsys=capsys)

    assert {name: script.is_file() for name, script in scripts.items()} == {
        "goblinscript": False, "no person": False, "a person": True, "goblinscript in the inbox": False}
    assert not script_library.is_marked_generated(scripts["no person"])
    assert said[-2:] == ["Deleted: 2 made by GoblinScript, 1 written by no person",
                         "Left, since a person wrote them: 1"]


def test_a_second_apply_finds_only_what_a_person_wrote(library, capsys):
    _one_flick_of_each_kind_in_each_place(library)
    _run("--apply", capsys=capsys)

    said = _run("--apply", capsys=capsys)

    assert said[-3:] == ["  Total: 0 made by GoblinScript, 0 written by no person, 1 written by a person",
                         "Deleted: 0 made by GoblinScript, 0 written by no person",
                         "Left, since a person wrote them: 1"]


def test_until_origenerator_says_which_of_its_files_are_flicks_it_looks_at_none(library, tmp_path, capsys):
    checkout = tmp_path / "origenerator checkout"
    checkout.mkdir()
    (checkout / origenerator_gallery.PUBLISHED).write_text("{}", encoding="utf-8")

    said = _run("--origenerator", str(checkout), capsys=capsys)

    assert "  Origenerator has not said which of its files are flicks yet: 0 looked at" in said


def _origenerator_saying(tmp_path: Path, item_types: dict[str, str]) -> Path:
    checkout = tmp_path / "origenerator checkout"
    checkout.mkdir()
    (checkout / origenerator_gallery.PUBLISHED).write_text(
        json.dumps({origenerator_gallery.ITEM_TYPE_BY_WORKFLOW: item_types}), encoding="utf-8")
    return checkout


def _origenerators_script(tmp_path: Path, video: Path, written: dict) -> Path:
    script = funscript.places_a_script_may_be_kept(
        video, videos=video.parent, scripts=tmp_path / "origenerator scripts")[0]
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(json.dumps(written), encoding="utf-8")
    return script


def test_the_funscripts_of_origenerators_flicks_are_found_by_the_workflow_it_says_makes_them(
        library, tmp_path, capsys):
    checkout = _origenerator_saying(tmp_path, {"made-up loop": "flick", "made-up motion": "video"})
    flick = touch_video(library.origenerator / "loop five.mp4")
    video = touch_video(library.origenerator / "video two.mp4")
    a_gallery_of(library.gallery_db, [kept_at("made-1", flick, workflow_name="made-up loop"),
                                      kept_at("made-2", video, workflow_name="made-up motion")])
    flicks_script = _origenerators_script(tmp_path, flick, BY_A_PERSON)
    videos_script = _origenerators_script(tmp_path, video, BY_A_PERSON)

    said = _run("--origenerator", str(checkout), "--apply", capsys=capsys)

    assert (flicks_script.is_file(), videos_script.is_file()) == (False, True)
    assert ("  Origenerator's videos folder: 0 made by GoblinScript, 1 written by no person, "
            "0 written by a person (2 looked at, 1 of them flicks)") in said


def test_a_funscript_a_video_of_the_same_name_would_also_take_is_left(library, tmp_path, capsys):
    checkout = _origenerator_saying(tmp_path, {"made-up loop": "flick"})
    flick = touch_video(library.origenerator / "flicks" / "shared name.mp4")
    video = touch_video(library.origenerator / "videos" / "shared name.mp4")
    a_gallery_of(library.gallery_db, [kept_at("made-1", flick, workflow_name="made-up loop"),
                                      kept_at("made-2", video, workflow_name="made-up motion")])
    by_its_name_alone = tmp_path / "origenerator scripts" / "shared name.funscript"
    by_its_name_alone.parent.mkdir(parents=True, exist_ok=True)
    by_its_name_alone.write_text(json.dumps(BY_GOBLINSCRIPT), encoding="utf-8")

    said = _run("--origenerator", str(checkout), "--apply", capsys=capsys)

    assert by_its_name_alone.is_file()
    assert "Left, since a video of the same name may use them: 1" in said


def _written(script: Path, written: dict) -> Path:
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(json.dumps(written), encoding="utf-8")
    return script


def test_a_funscript_parked_under_a_flicks_name_is_found_in_unmatched_scripts(library, capsys):
    touch_video(library.genau_flicks / "2D" / "AI" / "loop six_topaz.mp4")
    parked = [_written(library.unmatched / name, BY_GOBLINSCRIPT)
              for name in ("loop six.funscript", "loop six (2).funscript", "loop six_topaz.funscript")]
    not_a_flicks = _written(library.unmatched / "nothing known.funscript", BY_GOBLINSCRIPT)

    said = _run("--apply", capsys=capsys)

    assert ([script.is_file() for script in parked], not_a_flicks.is_file()) == ([False, False, False], True)
    assert "  `unmatched_scripts`: 3 made by GoblinScript, 0 written by no person, 0 written by a person" in said


def test_a_funscript_left_where_a_retired_genau_lane_copy_was_is_found_by_where_it_is(library, capsys):
    left = _written(library.scripts / "2D" / "AI" / "1_sorted" / GENAU_SOURCE / "portrait" / "loop gone.funscript",
                    BY_GOBLINSCRIPT)

    said = _run("--apply", capsys=capsys)

    assert not left.is_file()
    assert said[6] == ("  Scripts folder, Genau lane, video gone: 1 made by GoblinScript, 0 written by no person, "
                       "0 written by a person")


def test_a_parked_funscript_a_video_outside_the_genau_lane_is_also_named_for_is_left(library, capsys):
    touch_video(library.genau_flicks / "2D" / "AI" / "same name.mp4")
    touch_video(library.kino_upscales / "portrait" / "example-source" / "same name.mp4")
    parked = _written(library.unmatched / "same name.funscript", BY_GOBLINSCRIPT)

    said = _run("--apply", capsys=capsys)

    assert parked.is_file()
    assert "Left, since a video of the same name may use them: 1" in said


def test_a_funscript_beside_an_archived_video_is_that_videos(library, tmp_path, capsys):
    touch_video(library.genau_flicks / "2D" / "AI" / "kept name.mp4")
    touch_video(tmp_path / "archive" / "Jane Doe" / "kept name.mp4")
    beside_it = _written(tmp_path / "archive" / "Jane Doe" / "kept name.funscript", BY_GOBLINSCRIPT)

    said = _run("--apply", capsys=capsys)

    assert beside_it.is_file()
    assert "Left, since a video of the same name may use them: 1" in said


def test_a_parked_funscript_under_the_enhanced_name_of_an_origenerator_flick_is_found(library, tmp_path, capsys):
    checkout = _origenerator_saying(tmp_path, {"made-up loop": "flick"})
    a_gallery_of(library.gallery_db, [kept_at("made-1", library.origenerator / "gone loop.mp4",
                                              workflow_name="made-up loop")])
    parked = _written(library.unmatched / "gone loop_topaz.funscript", BY_GOBLINSCRIPT)

    _run("--origenerator", str(checkout), "--apply", capsys=capsys)

    assert not parked.is_file()


def test_until_origenerator_says_which_of_its_files_are_flicks_a_parked_one_of_its_names_is_left(
        library, tmp_path, capsys):
    a_gallery_of(library.gallery_db, [kept_at("made-1", library.origenerator / "gone loop.mp4",
                                              workflow_name="made-up loop")])
    parked = _written(library.unmatched / "gone loop_topaz.funscript", BY_GOBLINSCRIPT)

    _run(capsys=capsys)
    _run("--apply", capsys=capsys)

    assert parked.is_file()
