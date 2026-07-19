"""Test package marker, and the overlay pin.

The suite runs against the committed example overlay, never the developer's
git-ignored content.local.json, so a run here matches a public checkout. This
must happen before any test module imports the app, which loads content at
import time.
"""
import content

content.LOCAL_CONTENT = content.EXAMPLE_CONTENT
