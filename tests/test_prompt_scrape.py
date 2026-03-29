import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tasks import prompt_scrape
from tests.temp_helpers import override_config, workspace_temp_dir


def _wrap_hyperlink(value: str) -> str:
    as_posix = value.replace("\\", "/")
    return f'"=HYPERLINK(""file:///{as_posix}"";""{value}"")"'


class TestPromptScrape(unittest.TestCase):
    def test_run_writes_mirrored_json_for_provider_video_with_source_image_prompts(self):
        from datetime import date

        with workspace_temp_dir() as root:
            outbox = root / "videos" / "videos" / "2D" / "AI" / "2_outbox"
            prompts_dir = root / "videos" / "prompts"
            favs_path = root / "favs.csv"
            video_path = outbox / "upscaled_by_orientation" / "portrait" / "provider" / "abc_topaz.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_text("x", encoding="utf-8")
            favs_path.write_text(
                "local_file,web_url\n"
                f'{_wrap_hyperlink(str(video_path))},"=HYPERLINK(""https://example.com/image/abc"";""https://example.com/image/abc"")"\n',
                encoding="utf-8",
            )

            with override_config(FUN_TIME_FAVS_FILE=favs_path, PROMPTS_DIR=prompts_dir, OUTBOX_DIR=outbox):
                with patch("tasks.prompt_scrape._find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape._fetch_dom", side_effect=self._fetch_dom_with_source_image):
                        with patch("tasks.prompt_scrape._today", return_value=date(2026, 3, 28)):
                            result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.scraped, 1)
            output_path = prompts_dir / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider" / "abc_topaz.json"
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

    def test_run_falls_back_to_filename_mapping_without_csv_row(self):
        from datetime import date

        with workspace_temp_dir() as root:
            outbox = root / "videos" / "videos" / "2D" / "AI" / "2_outbox"
            prompts_dir = root / "videos" / "prompts"
            favs_path = root / "favs.csv"
            video_path = outbox / "upscaled_by_orientation" / "landscape" / "provider" / "uuid-123_topaz.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_text("x", encoding="utf-8")
            favs_path.write_text("local_file,web_url\n", encoding="utf-8")

            with override_config(FUN_TIME_FAVS_FILE=favs_path, PROMPTS_DIR=prompts_dir, OUTBOX_DIR=outbox):
                with patch("tasks.prompt_scrape._find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape._fetch_dom", side_effect=self._fetch_dom_text_only) as fetch_dom:
                        with patch("tasks.prompt_scrape._today", return_value=date(2026, 3, 28)):
                            result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.scraped, 1)
            self.assertIn("https://example.com/image/uuid-123", fetch_dom.call_args_list[0].args[0])
            output_path = prompts_dir / "2_outbox" / "upscaled_by_orientation" / "landscape" / "provider" / "uuid-123_topaz.json"
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload,
                {
                    "video": {
                        "prompt": "text only video prompt",
                        "model": "Video v3",
                        "seed": "456",
                        "created": "2026-03-25",
                    },
                },
            )

    def test_run_skips_existing_json_and_non_provider_urls(self):
        with workspace_temp_dir() as root:
            outbox = root / "videos" / "videos" / "2D" / "AI" / "2_outbox"
            prompts_dir = root / "videos" / "prompts"
            favs_path = root / "favs.csv"
            provider_video = outbox / "upscaled_by_orientation" / "portrait" / "provider" / "one_topaz.mp4"
            provider2_video = outbox / "upscaled_by_orientation" / "portrait" / "provider2" / "two_topaz.mp4"
            provider_video.parent.mkdir(parents=True, exist_ok=True)
            provider2_video.parent.mkdir(parents=True, exist_ok=True)
            provider_video.write_text("x", encoding="utf-8")
            provider2_video.write_text("x", encoding="utf-8")
            existing_output = prompts_dir / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider" / "one_topaz.json"
            existing_output.parent.mkdir(parents=True, exist_ok=True)
            existing_output.write_text('{"video_prompt":"old"}\n', encoding="utf-8")
            favs_path.write_text(
                "local_file,web_url\n"
                f'{_wrap_hyperlink(str(provider_video))},https://example.com/image/one\n'
                f'{_wrap_hyperlink(str(provider2_video))},https://example.net/image/two\n',
                encoding="utf-8",
            )

            with override_config(FUN_TIME_FAVS_FILE=favs_path, PROMPTS_DIR=prompts_dir, OUTBOX_DIR=outbox):
                with patch("tasks.prompt_scrape._find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape._fetch_dom") as fetch_dom:
                        result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.skipped_existing, 1)
            self.assertEqual(result.skipped_non_provider, 1)
            fetch_dom.assert_not_called()

    def test_run_ignores_partial_video_files(self):
        with workspace_temp_dir() as root:
            outbox = root / "videos" / "videos" / "2D" / "AI" / "2_outbox"
            prompts_dir = root / "videos" / "prompts"
            favs_path = root / "favs.csv"
            final_video = outbox / "upscaled_by_orientation" / "portrait" / "provider" / "one_topaz.mp4"
            partial_video = outbox / "upscaled_by_orientation" / "portrait" / "provider" / "one.partial.deadbeef.mp4"
            final_video.parent.mkdir(parents=True, exist_ok=True)
            final_video.write_text("x", encoding="utf-8")
            partial_video.write_text("x", encoding="utf-8")
            favs_path.write_text("local_file,web_url\n", encoding="utf-8")

            with override_config(FUN_TIME_FAVS_FILE=favs_path, PROMPTS_DIR=prompts_dir, OUTBOX_DIR=outbox):
                with patch("tasks.prompt_scrape._find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape._fetch_dom", side_effect=self._fetch_dom_text_only):
                        result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.scraped, 1)
            self.assertFalse((prompts_dir / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider" / "one.partial.deadbeef.json").exists())

    def test_run_counts_fetch_failure_and_reports_not_ok(self):
        with workspace_temp_dir() as root:
            outbox = root / "videos" / "videos" / "2D" / "AI" / "2_outbox"
            prompts_dir = root / "videos" / "prompts"
            favs_path = root / "favs.csv"
            video_path = outbox / "upscaled_by_orientation" / "portrait" / "provider" / "fail_topaz.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_text("x", encoding="utf-8")
            favs_path.write_text(
                "local_file,web_url\n"
                f'{_wrap_hyperlink(str(video_path))},https://example.com/image/fail\n',
                encoding="utf-8",
            )

            with override_config(FUN_TIME_FAVS_FILE=favs_path, PROMPTS_DIR=prompts_dir, OUTBOX_DIR=outbox):
                with patch("tasks.prompt_scrape._find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape._fetch_dom", side_effect=RuntimeError("network error")):
                        result = prompt_scrape.run()

            self.assertFalse(result.ok)
            self.assertEqual(result.fetch_failures, 1)
            self.assertEqual(result.scraped, 0)

    @staticmethod
    def _fetch_dom_with_source_image(url: str, browser: Path) -> str:
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
    def _fetch_dom_text_only(url: str, browser: Path) -> str:
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
            '"styleValue":null,"action":["pov_gamma"],'
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
        self.assertEqual(result.action, "Pov Gamma")
        self.assertEqual(result.style, "")
        self.assertEqual(result.creativity, "7")


class TestCssSelector(unittest.TestCase):
    def test_query_selector_finds_nested_element(self):
        html = '<body><div class="outer"><div class="inner">found</div></div></body>'
        doc = prompt_scrape._parse_html_document(html)
        node = prompt_scrape._query_selector(doc, "body > div.outer > div.inner")
        self.assertIsNotNone(node)
        self.assertEqual(prompt_scrape._text_content(node).strip(), "found")

    def test_query_selector_returns_none_for_no_match(self):
        html = '<body><div class="other">text</div></body>'
        doc = prompt_scrape._parse_html_document(html)
        self.assertIsNone(prompt_scrape._query_selector(doc, "body > div.missing"))

    def test_query_selector_nth_child(self):
        html = '<body><div><span>first</span><span>second</span><span>third</span></div></body>'
        doc = prompt_scrape._parse_html_document(html)
        node = prompt_scrape._query_selector(doc, "body > div > span:nth-child(2)")
        self.assertIsNotNone(node)
        self.assertEqual(prompt_scrape._text_content(node).strip(), "second")

    def test_query_selector_escaped_class_names(self):
        html = '<body><div class="text-[#fefefe]">styled</div></body>'
        doc = prompt_scrape._parse_html_document(html)
        node = prompt_scrape._query_selector(doc, r"body > div.text-\[\#fefefe\]")
        self.assertIsNotNone(node)
        self.assertEqual(prompt_scrape._text_content(node).strip(), "styled")

    def test_image_page_url_from_src(self):
        self.assertEqual(
            prompt_scrape._image_page_url_from_src("https://cdn1.example.com/abc123"),
            "https://example.com/image/abc123",
        )
        self.assertEqual(prompt_scrape._image_page_url_from_src("https://cdn1.example.com/"), "")


class TestFallbackUrlForVideo(unittest.TestCase):
    def test_generates_provider_url_from_video_path(self):
        video = Path("C:/videos/2_outbox/upscaled_by_orientation/portrait/provider/abc_topaz.mp4")
        self.assertEqual(prompt_scrape._fallback_url_for_video(video), "https://example.com/image/abc")

    def test_returns_none_for_non_provider(self):
        video = Path("C:/videos/2_outbox/upscaled_by_orientation/portrait/provider2/abc_topaz.mp4")
        self.assertIsNone(prompt_scrape._fallback_url_for_video(video))


class TestExtractMetadataFields(unittest.TestCase):
    def test_extracts_label_value_pairs(self):
        html = """
        <div>
          <div><h2>Model</h2><h1>Video v3</h1></div>
          <div><h2>Seed</h2><h1>12345</h1></div>
          <div><h2>Style</h2><h1>Default</h1></div>
        </div>
        """
        doc = prompt_scrape._parse_html_document(html)
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
        doc = prompt_scrape._parse_html_document(html)
        result = prompt_scrape._extract_metadata_fields(doc)
        self.assertEqual(result["model"], "X Dream")
        self.assertEqual(result["creativity"], "Balance")

    def test_converts_created_to_date(self):
        from datetime import date
        html = '<div><h2>Created</h2><h1>2w ago</h1></div>'
        doc = prompt_scrape._parse_html_document(html)
        with patch("tasks.prompt_scrape._today", return_value=date(2026, 3, 28)):
            result = prompt_scrape._extract_metadata_fields(doc)
        self.assertEqual(result["created"], "2026-03-14")

    def test_ignores_unknown_labels(self):
        html = '<div><h2>Inpainted</h2><h1>No</h1><h2>Model</h2><h1>v3</h1></div>'
        doc = prompt_scrape._parse_html_document(html)
        result = prompt_scrape._extract_metadata_fields(doc)
        self.assertNotIn("inpainted", result)
        self.assertEqual(result["model"], "v3")

    def test_returns_empty_dict_when_no_fields(self):
        html = '<div><p>Hello world</p></div>'
        doc = prompt_scrape._parse_html_document(html)
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

        with patch("tasks.prompt_scrape._fetch_dom", return_value=html):
            with patch("tasks.prompt_scrape._today", return_value=date(2026, 3, 28)):
                payload = prompt_scrape._scrape_provider_video(
                    Path("vid1_topaz.mp4"),
                    "https://example.com/image/vid1",
                    Path("chrome.exe"),
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


class TestParseRelativeDate(unittest.TestCase):
    def test_days_ago(self):
        from datetime import date
        with patch("tasks.prompt_scrape._today", return_value=date(2026, 3, 28)):
            self.assertEqual(prompt_scrape._parse_relative_date("2d ago"), "2026-03-26")

    def test_weeks_ago(self):
        from datetime import date
        with patch("tasks.prompt_scrape._today", return_value=date(2026, 3, 28)):
            self.assertEqual(prompt_scrape._parse_relative_date("2w ago"), "2026-03-14")

    def test_months_ago(self):
        from datetime import date
        with patch("tasks.prompt_scrape._today", return_value=date(2026, 3, 28)):
            self.assertEqual(prompt_scrape._parse_relative_date("3mo ago"), "2025-12-28")

    def test_hours_ago(self):
        from datetime import date
        with patch("tasks.prompt_scrape._today", return_value=date(2026, 3, 28)):
            self.assertEqual(prompt_scrape._parse_relative_date("5h ago"), "2026-03-28")

    def test_passthrough_non_relative(self):
        self.assertEqual(prompt_scrape._parse_relative_date("2026-01-15"), "2026-01-15")

    def test_passthrough_empty(self):
        self.assertEqual(prompt_scrape._parse_relative_date(""), "")


if __name__ == "__main__":
    unittest.main()
