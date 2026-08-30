"""Pipeline stage constants shared by the progress popup and detail views."""

STAGES = [
    ("purge",     "Purge Weird",          "Delete 2_outbox/kinda_weird AI vids, their matching sources in 1_sorted, and their metadata"),
    ("metadata",  "Metadata Scrape",      "Scrape AI prompt metadata into mirrored JSON files"),
    ("sort",      "Sort Inbox",           "Move AI videos from 0_inbox into 1_sorted by source and orientation"),
    ("upscale",   "Upscale",              "Apply Topaz 60fps frame interpolation + 4x upscale + various AI enhancements to 1_sorted AI videos, placing them in 2_outbox"),
    ("upscale_non_ai", "Upscale non-AI",  "Supervise one detached Topaz encode of a 2D/non_AI video (apo-8 60fps + iris-2 toward 4K); with the toggle on, run it while the user is idle and the AI queue is drained, suspending it the moment they return"),
    ("verify",    "Correspondence Check", "Verify 1_sorted and 2_outbox are in 1-to-1 correspondence"),
    ("references", "Follow Moved Videos", "Repoint the suite's saved video paths — Clipper sessions, Scripture projects, Fun Time favorites and watch counts — at videos that have since moved"),
    ("bookmarks", "Bookmarks Sync",       "Sync Fun Time favorites into a Chrome bookmarks folder"),
    ("clip_scripts", "Clip Scripts",      "Cut each carved clip's funscript out of its source scene's, using the offset the clip was matched at"),
    ("scene_scripts", "Scene Scripts",    "Give an unscripted source scene a mostly-blank funscript holding its carved clip's, placed where the clip sits in it"),
    ("scripts",   "Scripts Sync",         "Align funscripts to mirror the video library tree"),
    ("group_non_ai", "Group non-AI",      "Record each 2D/non_AI clip's version family (original + processed variants) in a mirrored metadata sidecar"),
    ("dupes",     "Duplicate Check",      "Scan non_AI folder for likely duplicate videos, using exact filesize"),
]

ALL_STAGES = [key for key, _, _ in STAGES]
STAGE_LABELS = {key: label for key, label, _ in STAGES}
STAGE_TOOLTIPS = {key: tip for key, _, tip in STAGES}
STAGE_NUMBER = {key: i + 1 for i, (key, _, _) in enumerate(STAGES)}
