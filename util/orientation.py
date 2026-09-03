"""The two orientations the library files a video under, and the third answer.

``ffprobe`` reads one of these off a video's stream; the sort stage makes it a
folder name; four more stages walk those folders and compare against it. It was
a bare string in six modules, written ``("landscape", "portrait")`` in five and
``("portrait", "landscape")`` in the sixth -- where the order is not cosmetic,
because it decides which orientation the backfill tool asks a human about
first. Nothing connected the value ffprobe produces, the directory name a path
is built from, and the folder names a walk expects, so a typo in any of them
was a silently empty listing rather than an error.
"""

from __future__ import annotations

LANDSCAPE = "landscape"
PORTRAIT = "portrait"

# The third answer, and not a folder: a video ffprobe cannot measure is left
# where it is rather than guessed into one of the two.
UNKNOWN = "unknown"

# The order the sorted tree's orientation folders are made and walked in.
SORTED = (LANDSCAPE, PORTRAIT)
