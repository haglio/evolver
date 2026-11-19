from __future__ import annotations

from collections.abc import Callable

from evolver import stage_label
from gui.run_record import RunRecord, format_run_start
from util.alert import show_error

TITLE = "Evolver - Stage error"


class FailedStagesNotice:
    def __init__(self, *, show: Callable[..., object] | None = None) -> None:
        self._show = show
        self._showing = False

    def after_run(self, record: RunRecord) -> None:
        failed = [stage_label(stage.get("name", "")) for stage in record.stages
                  if stage.get("status") == "error"]
        if not failed or self._showing:
            return
        self._showing = True
        try:
            (self._show or show_error)(TITLE, _message(failed, record), same_error=", ".join(failed))
        finally:
            self._showing = False


def _message(failed: list[str], record: RunRecord) -> str:
    named = ", ".join(failed)
    stages = "stage" if len(failed) == 1 else "stages"
    return (f"The {named} {stages} failed in the run that started at "
            f"{format_run_start(record.started_at)}.\n\n"
            "Click that run's title in Run history to read its log.")
