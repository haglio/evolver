from pathlib import Path
import os

BASE_DIR     = Path(r"C:\path\to\suite-root")
PROJECT_DIR  = BASE_DIR / "projects" / "evolver"
FUN_TIME_PROJECT_DIR = BASE_DIR / "projects" / "fun_time"
FUN_TIME_FAVS_FILE = FUN_TIME_PROJECT_DIR / "favs.csv"
# Origenerator (a sibling video-generation app) is treated as a normal external
# content source: for videos it drops in 0_inbox/origenerator/, Evolver pulls the
# generation metadata straight from Origenerator's own gallery database, read-only
# (see tasks/origenerator_metadata.py). Origenerator never reaches into Evolver.
ORIGENERATOR_DB_PATH = BASE_DIR / "projects" / "origenerator" / "state" / "origenerator.db"
VIDEO_LIBRARY_DIR = BASE_DIR / "videos" / "videos"
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

LOG_FILE = PROJECT_DIR / "evolver.log"
RUNS_DIR = PROJECT_DIR / "runs"
GUI_SETTINGS_FILE = PROJECT_DIR / "gui_settings.json"

# Voice control for the metadata backfill tool. The model name is resolved and cached
# by vosk under ~/.cache/vosk, the same small English model Fun Time listens with.
# VOICE_DEVICE_INDEX of None takes the system default input; set it to an index from
# `python -m sounddevice` when the default is not the microphone you speak into.
VOICE_MODEL_NAME = "vosk-model-small-en-us-0.15"
VOICE_DEVICE_INDEX = None
VOICE_SAMPLE_RATE = 16000
VOICE_CONFIDENCE_THRESHOLD = 0.7


def active_outbox_dirs() -> list[Path]:
    return [OUTBOX_DIR]


def active_weird_dirs() -> list[Path]:
    return [WEIRD_DIR]
