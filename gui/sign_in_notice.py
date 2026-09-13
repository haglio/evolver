from __future__ import annotations

from gui.run_record import RunRecord
from util import topaz
from util.alert import show_error

TITLE = "Evolver - Topaz Sign-In Expired"
MESSAGE = (
    "Topaz Video's sign-in has expired, so Evolver is holding off on upscaling. "
    "Topaz can put its watermark on videos it upscales until you sign in again.\n\n"
    "Open the Topaz Video app and sign in. Upscaling starts again on its own."
)
_REMIND_AFTER_SECONDS = 24 * 3600


class SignInNotice:
    def __init__(self) -> None:
        self._shown_at: float | None = None

    def after_run(self, record: RunRecord, now: float) -> None:
        if not _held_for_sign_in(record):
            return
        if self._shown_at is not None and now - self._shown_at < _REMIND_AFTER_SECONDS:
            return
        self._shown_at = now
        show_error(TITLE, MESSAGE)


def _held_for_sign_in(record: RunRecord) -> bool:
    return any(
        stage.get("skip_reason") == topaz.SIGN_IN_EXPIRED
        or (stage.get("result") or {}).get("start_deferred") == topaz.SIGN_IN_EXPIRED
        for stage in record.stages
    )
