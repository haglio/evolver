from __future__ import annotations

from shared_ui.preview import Preview, preview_of

import config


def shown_as() -> Preview | None:
    return preview_of(config.PROJECT_DIR) if config.BRANCH_SESSION else None
