"""How two chart colors are compared, in the terms the eye sees them.

The stacked area chart draws every stage as a band in one column, so what
matters is not whether two ``STAGE_COLORS`` entries differ but whether a
reader can separate the bands they paint — which are drawn translucent over
white, and so are closer together than the colors themselves. Distance is
CIE76 Delta-E in CIE Lab, where the units mean something a threshold can be
argued from: ~2 is the smallest difference anyone sees, ~10 reads as two
colors rather than two shades.
"""
from __future__ import annotations

import math

from gui.stats_window import BAND_ALPHA


def band_fill(color) -> tuple[int, int, int]:
    """The pixel a stage's band actually paints: its color over white ground."""
    red, green, blue = color.getRgb()[:3] if hasattr(color, "getRgb") else color
    return tuple(
        round((channel * BAND_ALPHA + 255 * (255 - BAND_ALPHA)) / 255)
        for channel in (red, green, blue)
    )


def _to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def linear(channel: float) -> float:
        channel /= 255.0
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in rgb)
    x = (0.4124 * red + 0.3576 * green + 0.1805 * blue) / 0.95047
    y = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    z = (0.0193 * red + 0.1192 * green + 0.9505 * blue) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    """CIE76 Delta-E between two RGB triples."""
    return math.dist(_to_lab(first), _to_lab(second))
