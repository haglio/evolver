"""The pipeline's stages, declared once.

Every stage is a key, the name a person is shown, the sentence explaining it,
and the colour its band is drawn in — in the order ``run_pipeline`` runs them.
Nothing else declares any of that: the progress popup's bars, the run detail
table's names, tooltips and numbers, the stats chart's series and its legend
all read this list, and the pipeline's own order is checked against it as it
runs.

It lives beside the stages rather than in ``gui/`` because the pipeline is the
thing being described. The colour is a plain RGB triple for the same reason —
the headless CLI has no Qt, and the one window that paints it can build its own
``QColor`` at the edge where Qt begins.

A stage the pipeline emitted with no row here drew no progress bar, lost its
duration from the chart and took the number of the stage after it, for months
(bug 5). Two things stop that recurring: there is one list to add to rather
than four, and ``tests/test_stage_registry.py`` runs the pipeline and compares
what it emits against this.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stage:
    """One pipeline stage: what it is called, what it does, how it is drawn."""

    key: str
    label: str
    tooltip: str
    color: tuple[int, int, int]


STAGES: tuple[Stage, ...] = (
    Stage("strays", "Stray Files",
          "Repair a video whose extension separator is not a dot, send a funscript found in the video tree to its mirror path under the scripts, and report every other non-video file found there",
          (0xBA, 0xB0, 0xAC)),
    Stage("purge", "Purge Weird",
          "Delete 2_outbox/kinda_weird AI vids, their matching sources in 1_sorted, and their metadata",
          (0xF2, 0x8E, 0x2B)),
    Stage("metadata", "Metadata Scrape",
          "Scrape AI prompt metadata into mirrored JSON files",
          (0x14, 0x7D, 0x3C)),
    Stage("sort", "Sort Inbox",
          "Move AI videos from 0_inbox into 1_sorted by source and orientation",
          (0x38, 0x6A, 0x9C)),
    Stage("upscale", "Upscale",
          "Apply Topaz 60fps frame interpolation + 4x upscale + various AI enhancements to 1_sorted AI videos, placing them in 2_outbox",
          (0xED, 0xC9, 0x48)),
    Stage("genau_deliver", "Genau Delivery",
          "Move each upscaled Genau-lane clip out of 2_outbox into the folder Genau plays from, retiring the 1_sorted copy it was made from — both halves leave together or the upscale stage redoes the clip forever",
          (0x7B, 0x41, 0x73)),
    Stage("upscale_non_ai", "Upscale non-AI",
          "Supervise one detached Topaz encode of a 2D/non_AI video (apo-8 60fps + iris-2 toward 4K); with the toggle on, run it while the user is idle and the AI queue is drained, suspending it the moment they return",
          (0x76, 0x67, 0x47)),
    Stage("verify", "Correspondence Check",
          "Verify 1_sorted and 2_outbox are in 1-to-1 correspondence",
          (0xFF, 0x9D, 0x83)),
    Stage("references", "Follow Moved Videos",
          "Repoint the suite's saved video paths — Clipper sessions, Scripture projects, Fun Time favorites and watch counts — at videos that have since moved",
          (0x61, 0xCA, 0xF2)),
    Stage("bookmarks", "Bookmarks Sync",
          "Sync Fun Time favorites into a Chrome bookmarks folder",
          (0x4B, 0x96, 0x88)),
    Stage("clip_scripts", "Clip Scripts",
          "Cut each carved clip's funscript out of its source scene's, using the offset the clip was matched at",
          (0xF6, 0x70, 0x99)),
    Stage("scene_scripts", "Scene Scripts",
          "Give an unscripted source scene a mostly-blank funscript holding its carved clip's, placed where the clip sits in it",
          (0xDE, 0xB8, 0xC6)),
    Stage("scripts", "Scripts Sync",
          "Align funscripts to mirror the video library tree",
          (0xAD, 0x40, 0x35)),
    Stage("group_non_ai", "Group non-AI",
          "Record each 2D/non_AI clip's version family (original + processed variants) in a mirrored metadata sidecar",
          (0x6F, 0xDB, 0x9A)),
    Stage("dupes", "Duplicate Check",
          "Scan non_AI folder for likely duplicate videos, using exact filesize",
          (0xCA, 0x94, 0xDB)),
)

ALL_STAGES = [stage.key for stage in STAGES]
STAGE_LABELS = {stage.key: stage.label for stage in STAGES}
STAGE_TOOLTIPS = {stage.key: stage.tooltip for stage in STAGES}
STAGE_NUMBER = {stage.key: i + 1 for i, stage in enumerate(STAGES)}
