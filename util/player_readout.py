from __future__ import annotations

from PyQt6.QtCore import QLoggingCategory

# Qt's FFmpeg backend writes out every video it opens, the file's tags among it,
# and a video ComfyUI made carries its prompt in those tags. Origenerator found
# it in its launcher logs and turns the same category off (qt_messages.py there).
FORMAT_DUMP = "qt.multimedia.ffmpeg.mediadataholder"


def silence_the_ffmpeg_format_dump() -> None:
    QLoggingCategory.setFilterRules(f"{FORMAT_DUMP}.info=false")
