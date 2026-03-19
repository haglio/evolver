from pathlib import Path

BASE_DIR     = Path(r"C:\path\to\suite-root")
PROJECT_DIR  = BASE_DIR / "projects" / "evolver"
AI_DIR       = BASE_DIR / "videos" / "videos" / "2D" / "AI"

INBOX_DIR    = AI_DIR / "0_inbox"
SORTED_DIR   = AI_DIR / "1_sorted"
OUTBOX_DIR   = AI_DIR / "2_outbox"

OUT_UPSCALED_DIR = OUTBOX_DIR / "upscaled_by_orientation"
WEIRD_DIR        = OUTBOX_DIR / "kinda_weird"

SOURCES = ["provider", "provider2", "provider3"]

FFMPEG         = Path(r"C:\Program Files\Topaz Labs LLC\Topaz Video\ffmpeg.exe")
TVAI_MODEL_DIR = Path(r"C:\ProgramData\Topaz Labs LLC\Topaz Video\models")

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".m4v"}

CLEAN_EMPTY_INBOX_DIRS = True

LOG_FILE = PROJECT_DIR / "evolver.log"
