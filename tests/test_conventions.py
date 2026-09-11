"""One word per concept, held where a synonym could otherwise creep back.

The unit had four synonym pairs at once: the same Path called a clip in one
module and a video in the module it called on every decision; a tile's label
and the act it stands for used interchangeably, including for the control tiles
that are no act at all; one lone ``get_`` prefix among five sibling functions;
and a module exporting bare ``read`` and ``update``, which land as unqualified
verbs in whatever imports them.

The last is the one a gate can hold. ``util.sidecar`` is the format two apps
write, and a bare ``read(path)`` in a module that also reads settings, a CSV
and a browser profile says nothing about which. Its sibling ``util.script_library``
was always reached module-qualified and never had the problem, so the rule is
that shape rather than a rename: ``sidecar.read``, not ``read``.
"""
from __future__ import annotations

import ast
import unittest

from tests.product_sources import PROJECT_ROOT, product_sources

# The verbs that must stay under their module's name. Names that describe what they
# answer -- ``sidecar_path``, ``action_of`` -- carry their subject with them
# and are fine imported bare.
_QUALIFIED_ONLY = frozenset({"read", "update", "write"})


def _bare_verb_imports(tree: ast.AST) -> list[str]:
    """``<line>:<name>`` for each verb imported out of ``util.sidecar``."""
    return [
        f"{node.lineno}:{alias.name}"
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "util.sidecar"
        for alias in node.names
        if alias.name in _QUALIFIED_ONLY
    ]


class TestOneWordPerConcept(unittest.TestCase):
    def test_the_sidecars_verbs_are_reached_through_their_module(self):
        offenders = sorted(
            f"{name}:{site}"
            for name in product_sources(PROJECT_ROOT)
            for site in _bare_verb_imports(
                ast.parse((PROJECT_ROOT / name).read_text(encoding="utf-8")))
        )

        self.assertEqual(
            offenders,
            [],
            "`from util import sidecar` and `sidecar.read(...)`, so the verb "
            "says what it reads",
        )


if __name__ == "__main__":
    unittest.main()
