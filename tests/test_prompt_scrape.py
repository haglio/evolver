import json
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from tasks import prompt_scrape
from tests.temp_helpers import workspace_temp_dir


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

            saved = {
                "FUN_TIME_FAVS_FILE": config.FUN_TIME_FAVS_FILE,
                "PROMPTS_DIR": config.PROMPTS_DIR,
                "OUTBOX_DIR": config.OUTBOX_DIR,
                "REGEN_OUTBOX_DIR": config.REGEN_OUTBOX_DIR,
                "REGEN_ENABLED": config.REGEN_ENABLED,
            }
            config.FUN_TIME_FAVS_FILE = favs_path
            config.PROMPTS_DIR = prompts_dir
            config.OUTBOX_DIR = outbox
            config.REGEN_OUTBOX_DIR = root / "videos" / "videos" / "2D" / "AI" / "3_new_outbox"
            config.REGEN_ENABLED = False
            try:
                with patch("tasks.prompt_scrape._find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape._fetch_dom", side_effect=self._fetch_dom_with_source_image):
                        result = prompt_scrape.run()
            finally:
                for key, value in saved.items():
                    setattr(config, key, value)

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

            saved = {
                "FUN_TIME_FAVS_FILE": config.FUN_TIME_FAVS_FILE,
                "PROMPTS_DIR": config.PROMPTS_DIR,
                "OUTBOX_DIR": config.OUTBOX_DIR,
                "REGEN_OUTBOX_DIR": config.REGEN_OUTBOX_DIR,
                "REGEN_ENABLED": config.REGEN_ENABLED,
            }
            config.FUN_TIME_FAVS_FILE = favs_path
            config.PROMPTS_DIR = prompts_dir
            config.OUTBOX_DIR = outbox
            config.REGEN_OUTBOX_DIR = root / "videos" / "videos" / "2D" / "AI" / "3_new_outbox"
            config.REGEN_ENABLED = False
            try:
                with patch("tasks.prompt_scrape._find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape._fetch_dom", side_effect=self._fetch_dom_text_only) as fetch_dom:
                        result = prompt_scrape.run()
            finally:
                for key, value in saved.items():
                    setattr(config, key, value)

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

            saved = {
                "FUN_TIME_FAVS_FILE": config.FUN_TIME_FAVS_FILE,
                "PROMPTS_DIR": config.PROMPTS_DIR,
                "OUTBOX_DIR": config.OUTBOX_DIR,
                "REGEN_OUTBOX_DIR": config.REGEN_OUTBOX_DIR,
                "REGEN_ENABLED": config.REGEN_ENABLED,
            }
            config.FUN_TIME_FAVS_FILE = favs_path
            config.PROMPTS_DIR = prompts_dir
            config.OUTBOX_DIR = outbox
            config.REGEN_OUTBOX_DIR = root / "videos" / "videos" / "2D" / "AI" / "3_new_outbox"
            config.REGEN_ENABLED = False
            try:
                with patch("tasks.prompt_scrape._find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape._fetch_dom") as fetch_dom:
                        result = prompt_scrape.run()
            finally:
                for key, value in saved.items():
                    setattr(config, key, value)

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

            saved = {
                "FUN_TIME_FAVS_FILE": config.FUN_TIME_FAVS_FILE,
                "PROMPTS_DIR": config.PROMPTS_DIR,
                "OUTBOX_DIR": config.OUTBOX_DIR,
                "REGEN_OUTBOX_DIR": config.REGEN_OUTBOX_DIR,
                "REGEN_ENABLED": config.REGEN_ENABLED,
            }
            config.FUN_TIME_FAVS_FILE = favs_path
            config.PROMPTS_DIR = prompts_dir
            config.OUTBOX_DIR = outbox
            config.REGEN_OUTBOX_DIR = root / "videos" / "videos" / "2D" / "AI" / "3_new_outbox"
            config.REGEN_ENABLED = False
            try:
                with patch("tasks.prompt_scrape._find_browser_executable", return_value=Path("chrome.exe")):
                    with patch("tasks.prompt_scrape._fetch_dom", side_effect=self._fetch_dom_text_only):
                        result = prompt_scrape.run()
            finally:
                for key, value in saved.items():
                    setattr(config, key, value)

            self.assertTrue(result.ok)
            self.assertEqual(result.scraped, 1)
            self.assertFalse((prompts_dir / "2_outbox" / "upscaled_by_orientation" / "portrait" / "provider" / "one.partial.deadbeef.json").exists())

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


if __name__ == "__main__":
    unittest.main()
