from __future__ import annotations

from tests.product_sources import PROJECT_ROOT, literals_in, product_sources

_TOPAZS_OWN_WORDS = "util/topaz.py"


def _is_a_sentence(text: str) -> bool:
    return " " in text


def test_no_sentence_evolver_shows_or_logs_says_upscale():
    said = sorted(
        f"{name}: {literal.value}"
        for name in product_sources(PROJECT_ROOT) if name != _TOPAZS_OWN_WORDS
        for literal in literals_in(name)
        if "upscal" in literal.value.lower() and _is_a_sentence(literal.value))

    assert said == []
