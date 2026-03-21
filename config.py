from pathlib import Path

BASE_DIR     = Path(r"C:\path\to\suite-root")
PROJECT_DIR  = BASE_DIR / "projects" / "evolver"
AI_DIR       = BASE_DIR / "videos" / "videos" / "2D" / "AI"
NON_AI_DIR   = BASE_DIR / "videos" / "videos" / "2D" / "non_AI"

INBOX_DIR    = AI_DIR / "0_inbox"
SORTED_DIR   = AI_DIR / "1_sorted"
OUTBOX_DIR   = AI_DIR / "2_outbox"
REGEN_OUTBOX_DIR = AI_DIR / "3_new_outbox"

OUT_UPSCALED_DIR = OUTBOX_DIR / "upscaled_by_orientation"
WEIRD_DIR        = OUTBOX_DIR / "kinda_weird"
REGEN_OUT_UPSCALED_DIR = REGEN_OUTBOX_DIR / "upscaled_by_orientation"
REGEN_WEIRD_DIR        = REGEN_OUTBOX_DIR / "kinda_weird"

FFMPEG         = Path(r"C:\Program Files\Topaz Labs LLC\Topaz Video\ffmpeg.exe")
TVAI_MODEL_DIR = Path(r"C:\ProgramData\Topaz Labs LLC\Topaz Video\models")

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v"}

CLEAN_EMPTY_INBOX_DIRS = True

UPSCALE_BATCH_LIMIT = 5
REGEN_ENABLED = True
DELETE_OLD_OUTBOX_AFTER_REGEN_SUCCESS = True
LOW_DISK_WARNING_GB = 250
ENABLE_CPU_BUSY_SKIP = True
CPU_BUSY_SKIP_THRESHOLD_PCT = 65.0
CPU_BUSY_SKIP_SAMPLE_SECONDS = 0.75
AUTO_CUTOVER_ON_REGEN_COMPLETE = True

LOG_FILE = PROJECT_DIR / "evolver.log"
REGEN_COMPLETE_MARKER = PROJECT_DIR / ".regen-complete"


def regen_mode_active() -> bool:
    return REGEN_ENABLED and not REGEN_COMPLETE_MARKER.exists()


def active_outbox_dirs() -> list[Path]:
    if regen_mode_active():
        return [OUTBOX_DIR, REGEN_OUTBOX_DIR]
    return [OUTBOX_DIR]


def active_weird_dirs() -> list[Path]:
    if regen_mode_active():
        return [WEIRD_DIR, REGEN_WEIRD_DIR]
    return [WEIRD_DIR]
