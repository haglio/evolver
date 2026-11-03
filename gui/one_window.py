from __future__ import annotations

from collections.abc import Callable


class OneWindow:
    def __init__(self):
        self.current = None

    @property
    def is_on_screen(self) -> bool:
        return self.current is not None and self.current.isVisible()

    def show(self, build: Callable[[], object]):
        if self.is_on_screen:
            self.current.raise_()
            self.current.activateWindow()
            return None
        if self.current is not None:
            self.current.close()
            self.current.deleteLater()
        self.current = build()
        self.current.show()
        return self.current
