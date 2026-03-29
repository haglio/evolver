from pathlib import Path
import os

BASE_DIR     = Path(r"C:\path\to\suite-root")
PROJECT_DIR  = BASE_DIR / "projects" / "evolver"
FUN_TIME_PROJECT_DIR = BASE_DIR / "projects" / "fun_time"
FUN_TIME_FAVS_FILE = FUN_TIME_PROJECT_DIR / "favs.csv"
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
RESCRAPE_BATCH_LIMIT = 50
UPSCALE_RUN_BUDGET_SECONDS = 8 * 60
UPSCALE_MIN_START_REMAINING_SECONDS = 2 * 60
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
FUN_TIME_CONFIG_FILE = FUN_TIME_PROJECT_DIR / "fun_time_config.json"


def active_outbox_dirs() -> list[Path]:
    return [OUTBOX_DIR]


def active_weird_dirs() -> list[Path]:
    return [WEIRD_DIR]


def ai_funscripted_dupes_dir() -> Path:
    return VIDEO_LIBRARY_DIR / "2D" / "non_AI" / "actually_AI_but_funscripted"
