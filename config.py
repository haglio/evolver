from pathlib import Path
import os

BASE_DIR     = Path(r"C:\path\to\suite-root")
PROJECT_DIR  = BASE_DIR / "projects" / "evolver"
FUN_TIME_PROJECT_DIR = BASE_DIR / "projects" / "fun_time"
FUN_TIME_FAVS_FILE = FUN_TIME_PROJECT_DIR / "favs.csv"
# Fun Time's per-video watch counts ("breeding" data), read-only. Satellite VLC
# plays populate it today; Nau plays will land in the same file once Fun Time's
# primary-library tracking exists. Keys are normalized as path.strip().lower().
FUN_TIME_WATCH_STATS_FILE = FUN_TIME_PROJECT_DIR / "state" / "watch_stats.json"
# Origenerator (a sibling video-generation app) is treated as a normal external
# content source: for videos it drops in 0_inbox/origenerator/, Evolver pulls the
# generation metadata straight from Origenerator's own gallery database, read-only
# (see tasks/origenerator_metadata.py). Origenerator never reaches into Evolver.
ORIGENERATOR_DB_PATH = BASE_DIR / "projects" / "origenerator" / "state" / "origenerator.db"
# Sibling apps that record a video's path in their own saved work. Evolver moves
# videos, so it owns keeping these pointed at the right file (see
# tasks/reference_sync.py); left alone they strand hand-made clip bounds,
# transcript splits, and favorites on paths that no longer exist.
CLIPPER_SESSIONS_DIR = BASE_DIR / "projects" / "clipper" / "sessions"
SCRIPTURE_SESSIONS_DIR = BASE_DIR / "projects" / "scripture" / "sessions"
VIDEO_LIBRARY_DIR = BASE_DIR / "videos" / "videos"
# Where to hunt for a video a stored reference has lost track of. Wider than the
# library itself, because videos also get parked in sibling folders such as
# _winston_compilations_archive/ — a reference into one of those still deserves
# to be followed rather than dropped.
VIDEO_SEARCH_ROOT = BASE_DIR / "videos"
METADATA_DIR = BASE_DIR / "videos" / "metadata"
SCRIPT_LIBRARY_DIR = BASE_DIR / "videos" / "scripts" / "scripts"
AI_DIR       = BASE_DIR / "videos" / "videos" / "2D" / "AI"
NON_AI_DIR   = BASE_DIR / "videos" / "videos" / "2D" / "non_AI"
CHROME_USER_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
CHROME_PROFILE_NAME = "Blair"
CHROME_BOOKMARKS_FOLDER_NAME = "Fun Time Favs"

INBOX_DIR    = AI_DIR / "0_inbox"
SORTED_DIR   = AI_DIR / "1_sorted"
OUTBOX_DIR   = AI_DIR / "2_outbox"

OUT_UPSCALED_DIR = OUTBOX_DIR / "upscaled_by_orientation"
WEIRD_DIR        = OUTBOX_DIR / "kinda_weird"

FFMPEG         = Path(r"C:\Program Files\Topaz Labs LLC\Topaz Video\ffmpeg.exe")
TVAI_MODEL_DIR = Path(r"C:\ProgramData\Topaz Labs LLC\Topaz Video\models")

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v"}
FUNSCRIPT_EXTENSION = ".funscript"

CLEAN_EMPTY_INBOX_DIRS = True

UPSCALE_BATCH_LIMIT = 5
UPSCALE_RUN_BUDGET_SECONDS = 8 * 60
UPSCALE_MIN_START_REMAINING_SECONDS = 2 * 60
PIPELINE_WALL_TIMEOUT_SECONDS = UPSCALE_RUN_BUDGET_SECONDS + 3 * 60  # 11 min
LOW_DISK_WARNING_GB = 250
ENABLE_CPU_BUSY_SKIP = True
CPU_BUSY_SKIP_THRESHOLD_PCT = 65.0
CPU_BUSY_SKIP_SAMPLE_SECONDS = 0.75
UPSCALE_FILTER_DEFAULT = (
    "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=1:instances=1,"
    "tvai_up=model=gcg-5:scale=4:device=0:vram=1:instances=1"
)
UPSCALE_FILTER_T2V_provider = (
    "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=1:instances=1,"
    "tvai_up=model=prob-4:scale=4:preblur=0:noise=0.33:details=0.33:"
    "halo=0:blur=0.67:compression=0:estimate=20:device=0:vram=1:instances=1"
)
VIDEOAI_TAG_DEFAULT = "Processed using apo-8 for 60 fps interpolation and gcg-5 for 4x upscale"
VIDEOAI_TAG_T2V_provider = "Processed using apo-8 for 60 fps interpolation and prob-4 for 4x upscale (t2v provider)"

# Non-AI library upscaling. The recipe replicates what the manually processed
# clips under 2D/non_AI carry in their videoai tags: apo-8 60 fps interpolation,
# then an iris-2 upscale in auto mode with recover-original-detail at 100
# (blend=1), aimed at a 4K frame. These encodes run for hours, so the stage
# launches one detached ffmpeg at a time and checks on it each scheduler tick.
NONAI_EXCLUDED_BUCKETS = {"actually_AI_but_funscripted"}  # AI-pipeline outputs parked in non_AI
# Version families the naming rule cannot see. It reunites an original with a
# variant whose stem is the original's plus a Topaz suffix; a version saved under
# a name of its own keeps no such thread back, so it is declared here instead.
# Maps that stem to the stem of the video it is a version of — both must sit in
# the same bucket, and with three versions point them all at the same one.
NONAI_VERSION_OVERRIDES = {
    # A 4K60 upscale of the best eight minutes of a 19.6-minute scene, kept
    # alongside the full-length original because the upscale is better than
    # anything the pipeline produces.
    "redacted POV BJ 4k 60fps": "redacted_540-pacI21CK",
}
# vram=0.5 and instances=0 (vs the AI stage's vram=1/instances=1): an unattended
# multi-hour encode shares the machine with whatever else is running, so it gets
# half the VRAM budget and no extra model instance — slower, but far harder to
# push the box into memory exhaustion.
NONAI_UPSCALE_FILTER_TEMPLATE = (
    "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=0.5:instances=0,"
    "tvai_up=model=iris-2:scale=0:w={width}:h={height}:preblur=0:noise=0:details=0:"
    "halo=0:blur=0:compression=0:estimate=20:blend=1:device=0:vram=0.5:instances=0"
)
NONAI_TARGET_LONG_EDGE = 3840
NONAI_TARGET_SHORT_EDGE = 2160
VIDEOAI_TAG_NONAI = (
    "Processed using apo-8 for 60 fps interpolation and iris-2 in auto mode "
    "with recover original detail at 100 for upscale toward 4K"
)
NONAI_OUTPUT_SUFFIX = "_apo8_iris2"
NONAI_PROCESSED_DIR_NAME = "processed"
NONAI_FALLBACK_DONE_DIR_NAME = "3_good_to_go"
# Rewrite-heavy runtime state lives OUTSIDE the synced project tree: the file
# sync service covering the project dir kept renaming the in-flight job file to
# "nonai_upscale_job [conflicted N].json" mid-run, which orphaned live encodes
# (they piled up unsupervised and crashed the machine). LOCALAPPDATA is local-only.
NONAI_STATE_DIR = Path(os.environ.get("LOCALAPPDATA", str(PROJECT_DIR))) / "Evolver"
NONAI_JOB_STATE_FILE = NONAI_STATE_DIR / "nonai_upscale_job.json"
NONAI_ATTEMPTS_FILE = NONAI_STATE_DIR / "nonai_upscale_attempts.json"
NONAI_COOLDOWN_FILE = NONAI_STATE_DIR / "nonai_upscale_cooldown.json"
NONAI_FFMPEG_LOG = NONAI_STATE_DIR / "nonai_upscale_ffmpeg.log"
NONAI_SKIP_MANIFEST = PROJECT_DIR / ".nonai-upscale-skip.txt"  # user-editable, stays visible
# The counterpart to the skip list: videos to encode next, in the order listed.
# A pin outranks every ordering heuristic and re-queues a video the bucket
# already holds an older processed variant of, which is the only way to ask for
# a redo under a newer recipe.
NONAI_PRIORITY_MANIFEST = PROJECT_DIR / ".nonai-upscale-next.txt"
NONAI_MAX_RUNTIME_HOURS = 24
NONAI_MAX_ATTEMPTS = 2
NONAI_COMPLETE_DURATION_FRACTION = 0.98
NONAI_MIN_AVAILABLE_RAM_GB = 8.0
NONAI_COOLDOWN_MINUTES = 30
# Presence throttle: once the toggle is on, Evolver auto-manages the encode by
# how long the user has been away from the keyboard/mouse. Below this idle
# threshold the user counts as present — no new encode starts and any in-flight
# one is suspended (frozen, zero compute); past it the machine is "away" and an
# encode may start or resume. Five minutes rides out ordinary reading/watching
# pauses without treating them as the user leaving.
NONAI_USER_IDLE_THRESHOLD_SECONDS = 300.0
# The GUI polls presence far more often than the 10-minute pipeline tick, so a
# returning user parks the encode within seconds instead of minutes.
NONAI_PRESENCE_POLL_SECONDS = 20.0

LOG_FILE = PROJECT_DIR / "evolver.log"
RUNS_DIR = PROJECT_DIR / "runs"
GUI_SETTINGS_FILE = PROJECT_DIR / "gui_settings.json"

# Voice control for the metadata backfill tool. The model name is resolved and cached
# by vosk under ~/.cache/vosk, the same small English model Fun Time listens with.
# VOICE_DEVICE_NAME pins the mic by a name-substring — set to "Brio" because a Pimax
# update made a dead VR mic the Windows default, which would feed vosk silence. Set it
# to None to instead auto-pick the liveliest live input (a brief probe that steps over
# a silent default); `python -m sounddevice` lists the names.
VOICE_MODEL_NAME = "vosk-model-small-en-us-0.15"
VOICE_DEVICE_NAME = "Brio"
VOICE_SAMPLE_RATE = 16000
VOICE_CONFIDENCE_THRESHOLD = 0.7

# One example frame per act, cached for the backfill window's clickable tiles. Local
# only (like the non-AI state above) and disposable — delete the folder to rebuild.
BACKFILL_THUMBNAIL_DIR = Path(os.environ.get("LOCALAPPDATA", str(PROJECT_DIR))) / "Evolver" / "backfill_thumbnails"


def active_outbox_dirs() -> list[Path]:
    return [OUTBOX_DIR]


def active_weird_dirs() -> list[Path]:
    return [WEIRD_DIR]
