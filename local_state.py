from __future__ import annotations

import os
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parent
# pCloud renamed a job file it saw rewritten mid-run ("[conflicted N]"), orphaning live encodes
# until the computer crashed; Windows' LOCALAPPDATA is never synced, so such files live under it.
LOCAL_STATE_DIR = Path(os.environ.get("LOCALAPPDATA", str(CHECKOUT))) / "Evolver"
