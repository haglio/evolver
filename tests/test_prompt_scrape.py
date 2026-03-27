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
                        result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.scraped, 1)
            output_path = prompts_dir / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider" / "abc_topaz.json"
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload,
                {
                    "video_prompt": "video prompt text",
                    "source_image_positive_prompt": "positive prompt text",
                    "source_image_negative_prompt": "negative prompt text",
                },
            )

    def test_run_falls_back_to_filename_mapping_without_csv_row(self):
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
                        result = prompt_scrape.run()

            self.assertTrue(result.ok)
            self.assertEqual(result.scraped, 1)
            self.assertIn("https://example.com/image/uuid-123", fetch_dom.call_args_list[0].args[0])
            output_path = prompts_dir / "2_outbox" / "upscaled_by_orientation" / "landscape" / "provider" / "uuid-123_topaz.json"
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"video_prompt": "text only video prompt"})

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
        if "/image/" in url:
            return """
            <body>
              <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
              <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
              <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
              <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
              <div></div>
              <div>
                <div class="relative flex h-full min-h-screen flex-col">
                  <main>
                    <div>
                      <div class="mt-2 w-full max-w-full gap-x-2 rounded-sm p-2">
                        <div class="flex-1 overflow-hidden">
                          <div class="font-regular selection:bg-primary">
                            <div></div>
                            <div><div>positive prompt text</div></div>
                            <div class="max-h-80 overflow-y-auto rounded-sm p-2 text-[#fefefe]">negative prompt text</div>
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
          <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
          <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
          <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
          <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
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
          <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
          <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
          <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
          <div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>
          <div>
            <div class="relative flex h-full min-h-screen flex-col">
              <main>
                <div>
                  <div class="mt-2 w-full max-w-full gap-x-2 rounded-sm p-2">
                    <div class="flex-1 overflow-hidden">
                      <div class="font-regular selection:bg-primary">
                        <div></div>
                        <div><div>text only video prompt</div></div>
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


class TestFallbackUrlForVideo(unittest.TestCase):
    def test_generates_provider_url_from_video_path(self):
        video = Path("C:/videos/2_outbox/upscaled_by_orientation/portrait/provider/abc_topaz.mp4")
        self.assertEqual(prompt_scrape._fallback_url_for_video(video), "https://example.com/image/abc")

    def test_returns_none_for_non_provider(self):
        video = Path("C:/videos/2_outbox/upscaled_by_orientation/portrait/provider2/abc_topaz.mp4")
        self.assertIsNone(prompt_scrape._fallback_url_for_video(video))


if __name__ == "__main__":
    unittest.main()
