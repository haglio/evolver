from __future__ import annotations


class StageResult:
    @property
    def ok(self) -> bool:
        return True

    @property
    def needs_an_eye(self) -> bool:
        return False
