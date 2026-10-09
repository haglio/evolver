from __future__ import annotations

from shared_ui.colors import BG_BUTTON, BG_SECONDARY, BG_TERTIARY, BLUE, BORDER_SUBTLE, TEXT_MUTED
from shared_ui.spacing import BUTTON_GAP, BUTTON_PAD_H_TIGHT, BUTTON_PAD_V, BUTTON_RADIUS


def toolbar_rules() -> str:
    return f"""
    QToolBar {{
        spacing: {BUTTON_GAP}px;
    }}
    QToolButton {{
        background-color: {BG_BUTTON.name()};
        border: 1px solid {BORDER_SUBTLE.name()};
        border-radius: {BUTTON_RADIUS}px;
        {toolbar_padding(right=BUTTON_PAD_H_TIGHT)}
    }}
    QToolButton:hover {{
        background-color: {BG_TERTIARY.name()};
    }}
    QToolButton:pressed {{
        background-color: {BLUE.name()};
    }}
    QToolButton:disabled {{
        background-color: {BG_SECONDARY.name()};
        color: {TEXT_MUTED.name()};
    }}"""


def toolbar_padding(*, right: int) -> str:
    return f"padding: {BUTTON_PAD_V}px {right}px {BUTTON_PAD_V}px {BUTTON_PAD_H_TIGHT}px;"
