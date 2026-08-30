import dataclasses
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from tasks import prompt_scrape
from util import html_query
from tests.temp_helpers import override_config, workspace_temp_dir


class TestPromptScrape(unittest.TestCase):
    def _ai_dir(self, root):
        return root / "videos" / "videos" / "2D" / "AI"

    def _dirs(self, root):
        """The two directories the tests themselves reach into."""
        return self._ai_dir(root) / "1_sorted", root / "videos" / "metadata"

    def _make_video(self, sorted_dir, source, orient, name):
        video = sorted_dir / source / orient / name
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_text("x", encoding="utf-8")
        return video

    def _override(self, root):
        ai = self._ai_dir(root)
        sorted_dir, metadata_dir = self._dirs(root)
        return override_config(VIDEO_LIBRARY_DIR=root / "videos" / "videos",
                               AI_DIR=ai, SORTED_DIR=sorted_dir, METADATA_DIR=metadata_dir,
                               OUT_UPSCALED_DIR=ai / "2_outbox" / "upscaled_by_orientation")

    def _mirror_path(self, metadata_dir, orient, source, stem):
        return (metadata_dir / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation"
                / orient / source / f"{stem}_topaz.json")

    def _marker_path(self, metadata_dir, orient, source, stem):
        p = self._mirror_path(metadata_dir, orient, source, stem)
        return p.with_name(p.name + ".failed")

    def test_run_writes_mirrored_json_for_provider_video_with_source_image_prompts(self):
        from datetime import date

        with workspace_temp_dir() as root:
            sorted_dir, metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, config.PROVIDER_SOURCE, "portrait", "abc.mp4")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom", side_effect=self._fetch_dom_with_source_image):
                        with patch("util.relative_dates.today", return_value=date(2026, 3, 28)):
                            result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.newly_scraped, 1)
            output_path = self._mirror_path(metadata_dir, "portrait", config.PROVIDER_SOURCE, "abc")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload,
                {
                    "video": {
                        "prompt": "video prompt text",
                        "model": "Video v3",
                        "seed": "123",
                        "created": "2026-03-21",
                    },
                    "source_image": {
                        "positive_prompt": "positive prompt text",
                        "negative_prompt": "negative prompt text",
                        "model": "X Dream",
                        "seed": "999",
                        "created": "2026-03-26",
                        "style": "Realistic",
                        "creativity": "Balance",
                    },
                },
            )

    def test_a_video_outside_an_orientation_folder_is_never_scraped(self):
        """The guard against a stray sub-folder: a video not under
        landscape/ or portrait/ has no derivable mirror path, so scraping it
        would write its sidecar somewhere wrong -- deleting the skip used to
        change nothing (audit probe P9)."""
        with workspace_temp_dir() as root:
            sorted_dir, metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, config.PROVIDER_SOURCE, "extras", "stray.mp4")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=Path("chrome.exe")):
                    # A real (empty) document, so if the skip is ever removed
                    # the scrape fails loudly instead of chewing on a Mock.
                    with patch("tasks.prompt_scrape.fetch_dom", return_value="<html></html>") as fetch_dom:
                        result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.newly_scraped, 0)
            fetch_dom.assert_not_called()
            self.assertEqual(list(metadata_dir.rglob("*.json")), [])

    def test_run_no_scrape_strat_for_unknown_source(self):
        with workspace_temp_dir() as root:
            sorted_dir, _metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, "provider2", "portrait", "two.mp4")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom") as fetch_dom:
                        result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.no_scrape_strat, 1)
            fetch_dom.assert_not_called()

    def test_run_builds_origenerator_metadata_without_browser(self):
        """Origenerator metadata comes from its DB, so it needs no browser and
        lands at the same mirrored path Provider sidecars do."""
        with workspace_temp_dir() as root:
            sorted_dir, metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, "origenerator", "portrait", "wan22_i2v_00001_.mp4")
            payload = {"video": {"prompt": "a scene", "seed": "42"}}

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=None):
                    with patch("tasks.prompt_scrape.origenerator_metadata.build_metadata",
                               return_value=payload) as build:
                        result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.newly_scraped, 1)
            build.assert_called_once()
            out = self._mirror_path(metadata_dir, "portrait", "origenerator", "wan22_i2v_00001_")
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), payload)

    def test_run_ignores_partial_video_files(self):
        with workspace_temp_dir() as root:
            sorted_dir, metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, config.PROVIDER_SOURCE, "portrait", "one.mp4")
            self._make_video(sorted_dir, config.PROVIDER_SOURCE, "portrait", "one.partial.deadbeef.mp4")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom", side_effect=self._fetch_dom_text_only):
                        result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.newly_scraped, 1)
            self.assertFalse(self._mirror_path(metadata_dir, "portrait", config.PROVIDER_SOURCE, "one.partial.deadbeef").exists())

    def test_run_counts_error_and_reports_not_ok(self):
        with workspace_temp_dir() as root:
            sorted_dir, _metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, config.PROVIDER_SOURCE, "landscape", "fail.mp4")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom", side_effect=RuntimeError("network error")):
                        result = prompt_scrape.run()

            self.assertFalse(result.ok)
            self.assertEqual(result.errors, 1)
            self.assertEqual(result.newly_scraped, 0)

    def test_failed_scrape_writes_failure_marker(self):
        with workspace_temp_dir() as root:
            sorted_dir, metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, config.PROVIDER_SOURCE, "landscape", "fail.mp4")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom", side_effect=RuntimeError("source gone")):
                        result = prompt_scrape.run()

            self.assertEqual(result.errors, 1)
            self.assertTrue(self._marker_path(metadata_dir, "landscape", config.PROVIDER_SOURCE, "fail").exists())

    def test_skips_video_that_already_has_json(self):
        with workspace_temp_dir() as root:
            sorted_dir, metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, config.PROVIDER_SOURCE, "portrait", "abc.mp4")
            existing = self._mirror_path(metadata_dir, "portrait", config.PROVIDER_SOURCE, "abc")
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_text("{}", encoding="utf-8")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom", return_value="<html></html>") as fetch_dom:
                        result = prompt_scrape.run()

            self.assertEqual(result.already_scraped, 1)
            self.assertEqual(result.newly_scraped, 0)
            fetch_dom.assert_not_called()

    def test_skips_video_with_failure_marker(self):
        with workspace_temp_dir() as root:
            sorted_dir, metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, config.PROVIDER_SOURCE, "portrait", "abc.mp4")
            marker = self._marker_path(metadata_dir, "portrait", config.PROVIDER_SOURCE, "abc")
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("previously failed", encoding="utf-8")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom", return_value="<html></html>") as fetch_dom:
                        result = prompt_scrape.run()

            self.assertEqual(result.skipped_failed, 1)
            self.assertEqual(result.newly_scraped, 0)
            fetch_dom.assert_not_called()

    def test_run_scans_sorted_and_writes_metadata_at_outbox_mirror_path(self):
        """Metadata stage should scan 1_sorted and place JSONs where _is_t2v_provider expects them."""
        from datetime import date

        with workspace_temp_dir() as root:
            sorted_dir, metadata_dir = self._dirs(root)
            self._make_video(sorted_dir, config.PROVIDER_SOURCE, "portrait", "abc.mp4")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom", side_effect=self._fetch_dom_text_only):
                        with patch("util.relative_dates.today", return_value=date(2026, 3, 28)):
                            result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.newly_scraped, 1)

            # JSON must land where _is_t2v_provider looks:
            # METADATA_DIR / "2_outbox" / "upscaled_by_orientation" / <orient> / <source> / <stem>_topaz.json
            expected_path = self._mirror_path(metadata_dir, "portrait", config.PROVIDER_SOURCE, "abc")
            self.assertTrue(expected_path.exists(), f"Expected metadata at {expected_path}")
            payload = json.loads(expected_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["video"]["prompt"], "text only video prompt")

    @staticmethod
    def _fetch_dom_with_source_image(url: str, browser: Path, *, profile_dir: Path) -> str:
        if "/image/source-image-u1" in url:
            return """
            <body>
              <div>
                <div class="relative flex h-full min-h-screen flex-col">
                  <main>
                    <div>
                      <div class="mt-2 w-full max-w-full gap-x-2 rounded-sm p-2">
                        <div class="flex-1 overflow-hidden">
                          <div class="font-regular selection:bg-primary">
                            <div></div>
                            <div><div>positive prompt text</div></div>
                            <div><span>Negative prompt</span></div>
                            <div class="max-h-80 overflow-y-auto rounded-sm p-2 text-[#fefefe]">negative prompt text</div>
                            <div class="space-y-2.5 overflow-hidden">
                              <div><h2>Model</h2><h1>X Dream</h1></div>
                              <div><h2>Seed</h2><h1>999</h1></div>
                              <div><h2>Created</h2><h1>2d ago</h1></div>
                              <div><h2>Style</h2><h1>Realistic</h1></div>
                              <div class="h-0 opacity-0">
                                <div><h2>Creativity</h2><h1>Balance</h1></div>
                                <div><h2>Inpainted</h2><h1>No</h1></div>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </main>
                </div>
              </div>
            </body>
            """
        return """
        <body>
          <div>
            <div class="relative flex h-full min-h-screen flex-col">
              <main>
                <div>
                  <div class="mt-2 w-full max-w-full gap-x-2 rounded-sm p-2">
                    <div class="flex-1 overflow-hidden">
                      <div class="font-regular selection:bg-primary">
                        <div class="-mt-4 px-2 pb-4">
                          <div class="h-25 w-fit cursor-pointer rounded-xl border border-[#151515] bg-transparent p-2 text-white transition-all duration-200 ease-in-out will-change-transform hover:bg-[#0e0e0e] active:scale-[0.95] active:border-[#303030] active:bg-[#171717]">
                            <img src="https://cdn1.example.com/source-image-u1" />
                          </div>
                        </div>
                        <div><div>video prompt text</div></div>
                        <div class="space-y-2.5 overflow-hidden">
                          <div><h2>Model</h2><h1>Video v3</h1></div>
                          <div><h2>Seed</h2><h1>123</h1></div>
                          <div><h2>Created</h2><h1>1w ago</h1></div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </main>
            </div>
          </div>
        </body>
        """

    @staticmethod
    def _fetch_dom_text_only(url: str, browser: Path, *, profile_dir: Path) -> str:
        return """
        <body>
          <div>
            <div class="relative flex h-full min-h-screen flex-col">
              <main>
                <div>
                  <div class="mt-2 w-full max-w-full gap-x-2 rounded-sm p-2">
                    <div class="flex-1 overflow-hidden">
                      <div class="font-regular selection:bg-primary">
                        <div></div>
                        <div><div>text only video prompt</div></div>
                        <div class="space-y-2.5 overflow-hidden">
                          <div><h2>Model</h2><h1>Video v3</h1></div>
                          <div><h2>Seed</h2><h1>456</h1></div>
                          <div><h2>Created</h2><h1>3d ago</h1></div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </main>
            </div>
          </div>
        </body>
        """


class TestTheStagesTwoDirectoriesAreParameters(unittest.TestCase):
    """The tree walked and the browser's scratch profile are arguments.

    A sentinel wired to the wrong place -- or resolved once at import, past
    override_config -- would leave the stage walking the configured tree and
    writing the browser's profile into the checkout anyway, and nothing would
    say so.
    """

    def _override(self, root):
        ai = root / "videos" / "videos" / "2D" / "AI"
        return override_config(
            VIDEO_LIBRARY_DIR=root / "videos" / "videos", AI_DIR=ai,
            SORTED_DIR=ai / "1_sorted", METADATA_DIR=root / "videos" / "metadata",
            OUT_UPSCALED_DIR=ai / "2_outbox" / "upscaled_by_orientation")

    def test_the_tree_walked_is_the_one_the_parameter_names(self):
        with workspace_temp_dir() as root:
            elsewhere = root / "elsewhere"
            video = elsewhere / config.PROVIDER_SOURCE / "portrait" / "abc.mp4"
            video.parent.mkdir(parents=True)
            video.write_text("x", encoding="utf-8")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable",
                           return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom",
                               side_effect=RuntimeError("reached the page")):
                        result = prompt_scrape.run(sorted_dir=elsewhere)

            # The configured tree does not exist, so a stage still reading it
            # would find nothing at all and report zero of everything.
            self.assertEqual(result.errors, 1)

    def test_the_browser_gets_the_scratch_profile_the_parameter_names(self):
        with workspace_temp_dir() as root:
            elsewhere = root / "elsewhere"
            profile = root / "profile"
            video = elsewhere / config.PROVIDER_SOURCE / "portrait" / "abc.mp4"
            video.parent.mkdir(parents=True)
            video.write_text("x", encoding="utf-8")

            with self._override(root):
                with patch("tasks.prompt_scrape.find_browser_executable",
                           return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape.fetch_dom",
                               return_value="<html></html>") as fetch:
                        prompt_scrape.run(sorted_dir=elsewhere,
                                          browser_profile_dir=profile)

            self.assertEqual(fetch.call_args.kwargs["profile_dir"], profile)
            self.assertFalse(
                (config.PROJECT_DIR / ".tmp-prompt-browser-profile").exists())


class TestExtractProviderEmbeddedMetadata(unittest.TestCase):
    def test_extracts_prompt_from_embedded_json(self):
        html = '{"id":"abc123","prompt":"a beautiful scene","negative_prompt":"ugly","parent_image_id":"img456"}'
        result = prompt_scrape._extract_provider_embedded_metadata(html, "abc123")
        self.assertEqual(result.prompt, "a beautiful scene")
        self.assertEqual(result.negative_prompt, "ugly")
        self.assertEqual(result.parent_image_id, "img456")

    def test_returns_empty_when_no_match(self):
        result = prompt_scrape._extract_provider_embedded_metadata("<html>nothing</html>", "missing")
        self.assertEqual(result.prompt, "")
        self.assertEqual(result.negative_prompt, "")
        self.assertEqual(result.parent_image_id, "")

    def test_handles_null_negative_prompt(self):
        html = '{"id":"abc","prompt":"scene","negative_prompt":null,"parent_image_id":null}'
        result = prompt_scrape._extract_provider_embedded_metadata(html, "abc")
        self.assertEqual(result.prompt, "scene")
        self.assertEqual(result.negative_prompt, "")
        self.assertEqual(result.parent_image_id, "")

    def test_extracts_extended_metadata_fields(self):
        html = (
            '{"imageId":"abc123","prompt":"a beautiful scene","negative_prompt":null,'
            '"parent_image_id":null,"model":"Realism","version":"v3","seed":12345,'
            '"aspectRatio":"16:9","width":1280,"height":720,"quality":"720p",'
            '"styleValue":null,"action":["pov_beta"],'
            '"createdAt":"Fri, 13 Mar 2026 09:45:26 GMT","creativity":7}'
        )
        result = prompt_scrape._extract_provider_embedded_metadata(html, "abc123")
        self.assertEqual(result.model, "Realism")
        self.assertEqual(result.version, "v3")
        self.assertEqual(result.seed, "12345")
        self.assertEqual(result.aspect_ratio, "16:9")
        self.assertEqual(result.resolution, "1280x720")
        self.assertEqual(result.quality, "720p")
        self.assertEqual(result.created, "2026-03-13")
        self.assertEqual(result.action, "POV Beta")
        self.assertEqual(result.style, "")
        self.assertEqual(result.creativity, "7")


class TestTheEmbeddedFieldTable(unittest.TestCase):
    def test_every_declared_field_has_a_reader(self):
        """The thirteen readers were thirteen copies of the same three lines, so
        a fourteenth field arriving with no reader looked exactly like the other
        thirteen and read as absent forever. It has to answer here instead."""
        self.assertEqual(
            {name for name, _ in prompt_scrape._EMBEDDED_FIELDS},
            {field.name for field in
             dataclasses.fields(prompt_scrape._ProviderEmbeddedMetadata)},
        )

    def test_a_reader_answers_the_empty_string_when_its_field_is_absent(self):
        """The one shape the loop depends on: absent is "", never None, so a
        field already found is never overwritten and a missing one never has to
        be special-cased."""
        for name, extract in prompt_scrape._EMBEDDED_FIELDS:
            with self.subTest(field=name):
                self.assertEqual(extract("{}"), "")


class TestTitlecaseAction(unittest.TestCase):
    def test_title_cases_each_word(self):
        self.assertEqual(prompt_scrape._titlecase_action("two_words"), "Two Words")

    def test_keeps_the_pov_initialism_fully_upper(self):
        self.assertEqual(prompt_scrape._titlecase_action("pov_beta"), "POV Beta")
        self.assertEqual(prompt_scrape._titlecase_action("side_pov_gamma"), "Side POV Gamma")


class TestCssSelector(unittest.TestCase):
    """The DOM engine's public surface, in util.html_query."""
    def test_query_selector_finds_nested_element(self):
        html = '<body><div class="outer"><div class="inner">found</div></div></body>'
        doc = html_query.parse_document(html)
        node = html_query.query_selector(doc, "body > div.outer > div.inner")
        self.assertIsNotNone(node)
        self.assertEqual(html_query.text_content(node).strip(), "found")

    def test_query_selector_returns_none_for_no_match(self):
        html = '<body><div class="other">text</div></body>'
        doc = html_query.parse_document(html)
        self.assertIsNone(html_query.query_selector(doc, "body > div.missing"))

    def test_the_engine_answers_the_one_selector_production_asks_for(self):
        """Nothing builds a selector: there is one constant, of this shape."""
        html = (
            "<body><main><div><div>"
            '<div class="flex-1 overflow-hidden"><div class="font-regular">panel</div></div>'
            "</div></div></main></body>"
        )
        doc = html_query.parse_document(html)
        node = html_query.query_selector(doc, prompt_scrape._CONTENT_PANEL_SELECTOR)
        self.assertIsNotNone(node)
        self.assertEqual(html_query.text_content(node).strip(), "panel")

    def test_image_page_url_from_src(self):
        self.assertEqual(
            prompt_scrape._image_page_url_from_src("https://cdn1.example.com/abc123", config.PROVIDER_BASE_URL),
            f"{config.PROVIDER_BASE_URL}/image/abc123",
        )
        self.assertEqual(prompt_scrape._image_page_url_from_src("https://cdn1.example.com/", config.PROVIDER_BASE_URL), "")


class TestProviderImageUrl(unittest.TestCase):
    def test_generates_provider_url(self):
        video = Path("C:/videos/0_inbox/provider/abc.mp4")
        self.assertEqual(prompt_scrape._provider_image_url(video, config.PROVIDER_BASE_URL), f"{config.PROVIDER_BASE_URL}/image/abc")


class TestExtractMetadataFields(unittest.TestCase):
    def test_extracts_label_value_pairs(self):
        html = """
        <div>
          <div><h2>Model</h2><h1>Video v3</h1></div>
          <div><h2>Seed</h2><h1>12345</h1></div>
          <div><h2>Style</h2><h1>Default</h1></div>
        </div>
        """
        doc = html_query.parse_document(html)
        result = prompt_scrape._extract_metadata_fields(doc)
        self.assertEqual(result["model"], "Video v3")
        self.assertEqual(result["seed"], "12345")
        self.assertEqual(result["style"], "Default")

    def test_extracts_creativity_from_hidden_section(self):
        html = """
        <div>
          <div><h2>Model</h2><h1>X Dream</h1></div>
          <div class="h-0 opacity-0 hidden">
            <div><h2>Creativity</h2><h1>Balance</h1></div>
          </div>
        </div>
        """
        doc = html_query.parse_document(html)
        result = prompt_scrape._extract_metadata_fields(doc)
        self.assertEqual(result["model"], "X Dream")
        self.assertEqual(result["creativity"], "Balance")

    def test_converts_created_to_date(self):
        from datetime import date
        html = '<div><h2>Created</h2><h1>2w ago</h1></div>'
        doc = html_query.parse_document(html)
        with patch("util.relative_dates.today", return_value=date(2026, 3, 28)):
            result = prompt_scrape._extract_metadata_fields(doc)
        self.assertEqual(result["created"], "2026-03-14")

    def test_ignores_unknown_labels(self):
        html = '<div><h2>Inpainted</h2><h1>No</h1><h2>Model</h2><h1>v3</h1></div>'
        doc = html_query.parse_document(html)
        result = prompt_scrape._extract_metadata_fields(doc)
        self.assertNotIn("inpainted", result)
        self.assertEqual(result["model"], "v3")

    def test_returns_empty_dict_when_no_fields(self):
        html = '<div><p>Hello world</p></div>'
        doc = html_query.parse_document(html)
        result = prompt_scrape._extract_metadata_fields(doc)
        self.assertEqual(result, {})


class TestScrapeVideoEmbeddedMetadataFallback(unittest.TestCase):
    def test_uses_embedded_metadata_when_dom_panel_absent(self):
        from datetime import date

        html = (
            "<html><body>"
            '{"imageId":"vid1","prompt":"video prompt","negative_prompt":null,'
            '"parent_image_id":null,"model":"Realism","version":"v3","seed":99999,'
            '"aspectRatio":"9:16","width":720,"height":1280,"quality":"720p",'
            '"styleValue":"Default","action":["alpha"],'
            '"createdAt":"Fri, 13 Mar 2026 09:45:26 GMT","creativity":5}'
            "</body></html>"
        )

        with patch("tasks.prompt_scrape.fetch_dom", return_value=html):
            with patch("util.relative_dates.today", return_value=date(2026, 3, 28)):
                payload = prompt_scrape._scrape_provider_video(
                    Path("vid1_topaz.mp4"),
                    f"{config.PROVIDER_BASE_URL}/image/vid1",
                    Path("chrome.exe"),
                    config.PROVIDER_BASE_URL,
                    Path("profile"),
                )

        self.assertEqual(payload["video"]["prompt"], "video prompt")
        self.assertEqual(payload["video"]["model"], "Video v3")
        self.assertEqual(payload["video"]["seed"], "99999")
        self.assertEqual(payload["video"]["aspect_ratio"], "9:16")
        self.assertEqual(payload["video"]["resolution"], "720x1280")
        self.assertEqual(payload["video"]["quality"], "720p")
        self.assertEqual(payload["video"]["created"], "2026-03-13")
        self.assertEqual(payload["video"]["action"], "Alpha")
        self.assertEqual(payload["video"]["style"], "Default")
        self.assertNotIn("source_image", payload)


class TestProviderSettingsAreRedirectable(unittest.TestCase):
    """The scraped provider's name and site root come from the overlay, and
    used to be bound the first time this module was imported.

    Nothing could redirect them after that — not a caller, not a test — which
    is why they were read straight off ``load_content()`` at module level and
    why four of this module's imports sat below executable code. They are
    ordinary config values now, resolved when the stage runs.
    """

    def test_the_source_name_and_site_root_come_from_config_at_call_time(self):
        with override_config(
            PROVIDER_SOURCE="examplesource", PROVIDER_BASE_URL="https://example.invalid",
        ):
            strategies = prompt_scrape._build_strategies(
                Path("browser.exe"), Path("profile"))
            self.assertIn("examplesource", strategies)

            with patch("tasks.prompt_scrape._scrape_provider_video") as scrape:
                strategies["examplesource"](Path("abc_topaz.mp4"))

        _video, image_url, _browser, base_url, _profile = scrape.call_args.args
        self.assertEqual(image_url, "https://example.invalid/image/abc")
        self.assertEqual(base_url, "https://example.invalid")


if __name__ == "__main__":
    unittest.main()
