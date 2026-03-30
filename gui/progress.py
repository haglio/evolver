"""Pipeline stage constants shared by the progress popup and detail views."""

STAGES = [
    ("sort",      "Sort Inbox",           "Move AI videos from 0_inbox into 1_sorted by source and orientation"),
    ("purge",     "Purge Weird",          "Delete 2_outbox/kinda_weird AI vids, their matching sources in 1_sorted, and their metadata"),
    ("scripts",   "Scripts Sync",         "Align funscripts to mirror the video library tree"),
    ("bookmarks", "Bookmarks Sync",       "Sync Fun Time favorites into a Chrome bookmarks folder"),
    ("metadata",  "Metadata Scrape",      "Scrape AI prompt metadata into mirrored JSON files"),
    ("upscale",   "Upscale",              "Apply Topaz 60fps frame interpolation + 4x upscale + various AI enhancements to 1_sorted AI videos, placing them in 2_outbox"),
    ("dupes",     "Duplicate Check",      "Scan non_AI folder for likely duplicate videos, using exact filesize"),
    ("verify",    "Correspondence Check", "Verify 1_sorted and 2_outbox are in 1-to-1 correspondence"),
]

ALL_STAGES = [key for key, _, _ in STAGES]
STAGE_DISPLAY_NAMES = {key: name for key, name, _ in STAGES}
STAGE_TOOLTIPS = {key: tip for key, _, tip in STAGES}
STAGE_NUMBER = {key: i + 1 for i, (key, _, _) in enumerate(STAGES)}
