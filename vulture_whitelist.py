"""Vulture whitelist — false positives that are not dead code.

Each entry tells vulture the name is used, suppressing the report.
Only add names here that are *provably* called by a framework or
accessed dynamically at runtime.
"""

# -- Qt virtual-method overrides (called by the event loop) --
_.paintEvent  # noqa: F821
_.mousePressEvent  # noqa: F821
_.closeEvent  # noqa: F821
_.sizeHint  # noqa: F821
_.drawFocus  # noqa: F821
_.accept  # noqa: F821  — QDialog.accept

# -- Python HTMLParser overrides --
_.handle_starttag  # noqa: F821
_.handle_endtag  # noqa: F821
_.handle_startendtag  # noqa: F821
_.handle_data  # noqa: F821

# -- Script entry points (invoked by __main__ guard) --
_.main  # noqa: F821
