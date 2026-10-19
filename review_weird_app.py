#!/usr/bin/env pythonw
from __future__ import annotations

import sys

from shared_ui.application import application

import evolver
from gui import process_identity
from review_weird.window import ReviewWeirdWindow


def main() -> int:
    evolver.setup_logging()
    with application(sys.argv) as app:
        process_identity.claim(app)
        window = ReviewWeirdWindow()
        window.show()
        return app.exec()


if __name__ == "__main__":
    sys.exit(main())
