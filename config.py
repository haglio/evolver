from __future__ import annotations

import os
import tempfile
from datetime import tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app_support import haglio_settings, siblings
from app_support.flick_folder import trash_folder_in
from app_support.overlay import overlay_value

from content_overlay import LOCAL_CONTENT, load_content, refuse_an_incomplete_overlay

refuse_an_incomplete_overlay()
_CONTENT = load_content()

LIBRARY_ROOT = Path(haglio_settings.value("library_root"))


PROJECT_ROOTS = haglio_settings.project_roots()


def retired_root(content: dict[str, Any]) -> Path | None:
    configured = content.get("retired_root")
    return Path(configured) if configured else None


def project_dir(name: str, roots: tuple[Path, ...] | None = None) -> Path:
    return siblings.project_dir(name, PROJECT_ROOTS if roots is None else roots)


PROJECT_DIR  = Path(__file__).resolve().parent

BRANCH_SESSION_FLAG = "EVOLVER_BRANCH_SESSION"


def live_dir(environ: dict, project_dir_path: Path, roots: tuple[Path, ...]) -> Path:
    if environ.get(BRANCH_SESSION_FLAG) != "1":
        return project_dir_path
    return siblings.project_dir("evolver", roots)


LIVE_DIR = live_dir(os.environ, PROJECT_DIR, PROJECT_ROOTS)
BRANCH_SESSION = LIVE_DIR != PROJECT_DIR
FUN_TIME_PROJECT_DIR = project_dir("fun_time")
FUN_TIME_WATCH_STATS_FILE = FUN_TIME_PROJECT_DIR / "state" / "watch_stats.json"
ORIGENERATOR_PROJECT_DIR = project_dir("origenerator")
ORIGENERATOR_DB_PATH = ORIGENERATOR_PROJECT_DIR / "state" / "origenerator.db"
GENAUMACHER_SESSIONS_DIR = project_dir("genaumacher") / "sessions"
SCRIPTURE_SESSIONS_DIR = project_dir("scripture") / "sessions"
BROKER_TRAY_LAUNCHER = project_dir("broker") / "launch_broker_tray.vbs"
VIDEO_LIBRARY_DIR = LIBRARY_ROOT / "videos" / "videos"
VIDEO_SEARCH_ROOT = VIDEO_LIBRARY_DIR.parent
METADATA_DIR = LIBRARY_ROOT / "videos" / "metadata"


ORIGENERATOR_VIDEOS_DIR = Path(haglio_settings.value("origenerator_videos_dir"))


def warm_gun_outbox(content: dict[str, Any]) -> Path | None:
    outbox = content.get("warm_gun_outbox")
    return Path(outbox) if outbox else None


def warm_gun_journal_dirs(content: dict[str, Any], library_dir: Path) -> tuple[Path, ...]:
    outbox = warm_gun_outbox(content)
    return (library_dir, *([outbox] if outbox else []))


WARM_GUN_OUTBOX = warm_gun_outbox(_CONTENT)
WARM_GUN_JOURNAL_DIRS = warm_gun_journal_dirs(_CONTENT, Path(haglio_settings.value("warm_gun_journal_dir")))
SCRIPT_LIBRARY_DIR = LIBRARY_ROOT / "videos" / "scripts" / "scripts"
UNMATCHED_SCRIPTS_DIR = LIBRARY_ROOT / "videos" / "scripts" / "unmatched_scripts"
GENERATED_SCRIPTS_DIR = LIBRARY_ROOT / "videos" / "scripts" / "generated"


def vr_video_dir(content: dict[str, Any]) -> Path | None:
    configured = content.get("vr_videos")
    return Path(configured) if configured else None


VR_VIDEO_DIR = vr_video_dir(_CONTENT)
AI_DIR       = LIBRARY_ROOT / "videos" / "videos" / "2D" / "AI"
NON_AI_DIR   = LIBRARY_ROOT / "videos" / "videos" / "2D" / "non_AI"
CHROME_USER_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
CHROME_PROFILE_NAME = overlay_value(_CONTENT, "chrome_profile", path=LOCAL_CONTENT)
CHROME_BOOKMARKS_FOLDER_NAME = "Fun Time Favs"

INBOX_DIR    = AI_DIR / "0_inbox"
SORTED_DIR   = AI_DIR / "1_sorted"
OUTBOX_DIR   = AI_DIR / "2_outbox"

OUT_UPSCALED_DIR = OUTBOX_DIR / "upscaled_by_orientation"
TRASH_DIR        = OUTBOX_DIR / "trash"

GENAU_SOURCE    = haglio_settings.value("genau_source")
GENAU_FLICK_WORD = haglio_settings.value("genau_flick_words", "one")
GENAU_DIR = Path(haglio_settings.value("genau_dir"))
GENAU_AUDIO_DIR = Path(haglio_settings.value("genau_audio_dir"))
GENAU_TRASH_DIR = trash_folder_in(GENAU_DIR)


def kept_by_other_apps() -> tuple[Path, Path]:
    return GENAU_DIR, ORIGENERATOR_VIDEOS_DIR


_SCRAPE_PROVIDER = overlay_value(_CONTENT, "scrape_provider", path=LOCAL_CONTENT)
PROVIDER_SOURCE   = _SCRAPE_PROVIDER["source"]
PROVIDER_BASE_URL = _SCRAPE_PROVIDER["base_url"]
CAMERA_PREFIXES = tuple(
    camera["prefix"] for camera in overlay_value(_CONTENT, "cameras", path=LOCAL_CONTENT))
PROMPT_BROWSER_PROFILE_DIR = Path(tempfile.gettempdir()) / "evolver-prompt-browser-profile"

CLIP_FOLDERS = tuple(_CONTENT.get("excerpt_folders") or ())

# Only Topaz Video's own ffmpeg build has the tvai_* filters both upscale stages use, and the
# Topaz installer puts its models in a different tree from it.
_INSTALLED_TOPAZ_FFMPEG = r"C:\Program Files\Topaz Labs LLC\Topaz Video\ffmpeg.exe"
_INSTALLED_TOPAZ_MODELS = r"C:\ProgramData\Topaz Labs LLC\Topaz Video\models"


def topaz_paths(content: dict[str, Any]) -> tuple[Path, Path]:
    return (
        Path(content.get("topaz_ffmpeg") or _INSTALLED_TOPAZ_FFMPEG),
        Path(content.get("topaz_models") or _INSTALLED_TOPAZ_MODELS),
    )


FFMPEG, TVAI_MODEL_DIR = topaz_paths(_CONTENT)

def display_timezone(content: dict[str, Any]) -> tzinfo | None:
    name = content.get("display_timezone")
    return ZoneInfo(name) if name else None


DISPLAY_TIMEZONE = display_timezone(_CONTENT)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v"}
FUNSCRIPT_EXTENSION = ".funscript"

UPSCALE_BATCH_LIMIT = 5
VIDEO_KIND_PROBES_PER_RUN = 400
CLOUD_DRIVE_PROBES_PER_RUN = 10
UPSCALE_RUN_BUDGET_SECONDS = 8 * 60
UPSCALE_MIN_START_REMAINING_SECONDS = 2 * 60
PIPELINE_WALL_TIMEOUT_SECONDS = UPSCALE_RUN_BUDGET_SECONDS + 3 * 60
LOW_DISK_WARNING_GB = 25
CPU_BUSY_SKIP_THRESHOLD_PCT = 65.0
CPU_BUSY_SKIP_SAMPLE_SECONDS = 0.75

NONAI_VERSION_OVERRIDES: dict[str, str] = _CONTENT.get("version_overrides") or {}
NONAI_OUTPUT_SUFFIX = "_apo8_iris2"
NONAI_PROCESSED_DIR_NAME = "processed"
NONAI_FALLBACK_DONE_DIR_NAME = "3_good_to_go"
NONAI_RETIRED_ROOT = retired_root(_CONTENT)
# pCloud renamed a job file it saw rewritten mid-run ("[conflicted N]"), orphaning live encodes
# until the computer crashed; Windows' LOCALAPPDATA is never synced, so such files live under it.
LOCAL_STATE_DIR = Path(os.environ.get("LOCALAPPDATA", str(PROJECT_DIR))) / "Evolver"
NONAI_JOB_STATE_FILE = LOCAL_STATE_DIR / "nonai_upscale_job.json"
NONAI_ATTEMPTS_FILE = LOCAL_STATE_DIR / "nonai_upscale_attempts.json"
NONAI_COOLDOWN_FILE = LOCAL_STATE_DIR / "nonai_upscale_cooldown.json"
NONAI_REQUEST_FILE = LOCAL_STATE_DIR / "nonai_upscale_request.json"
LOW_DISK_WARNING_DISMISSED_FILE = LOCAL_STATE_DIR / "low_disk_warning_dismissed"
PIPELINE_LOCK_FILE = LOCAL_STATE_DIR / "pipeline.lock"
NONAI_FFMPEG_LOG = LOCAL_STATE_DIR / "nonai_upscale_ffmpeg.log"
WARM_GUN_FAVORITES_CURSOR_FILE = LOCAL_STATE_DIR / "warm_gun_favorites.json"
_LISTS_EDITED_BY_HAND_DIR = LIVE_DIR
NONAI_SKIP_LIST = _LISTS_EDITED_BY_HAND_DIR / ".nonai-upscale-skip.txt"
NONAI_PIN_LIST = _LISTS_EDITED_BY_HAND_DIR / ".nonai-upscale-next.txt"
NONAI_PRESENCE_POLL_SECONDS = 20.0

LOG_FILE = LIVE_DIR / "evolver.log"
RUNS_DIR = LIVE_DIR / "runs"
RUNS_SHOWN = 1000
GUI_SETTINGS_FILE = LIVE_DIR / "gui_settings.json"


