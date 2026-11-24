from __future__ import annotations

from pathlib import Path

from util import site_pages

_A_SITE = {"a-site": "https://a-site.example"}


def test_a_video_from_a_site_evolver_knows_has_that_sites_page_for_its_name():
    video = Path("kino/2D/AI/portrait/a-site/1234-abcd_topaz.mp4")

    assert site_pages.page_of(video, _A_SITE) == "https://a-site.example/image/1234-abcd"


def test_a_video_from_a_site_evolver_was_never_taught_has_no_page():
    assert site_pages.page_of(Path("kino/2D/AI/portrait/b-site/clip_topaz.mp4"), _A_SITE) is None
