import shutil
from pathlib import Path

from .logger import Logger
from qa_crawler.config import (
    CONTROL_SCREENSHOT_DIR,
    DIFF_SCREENSHOT_DIR,
    EXPERIMENTAL_SCREENSHOT_DIR,
    ensure_data_directories,
)


class ScreenshotLogger(Logger):
    def __init__(self):
        super().__init__()
        self.screenshot_count = 0
        self._clear_screenshot_directories()

    def _clear_screenshot_directories(self):
        ensure_data_directories()
        for directory in (CONTROL_SCREENSHOT_DIR, EXPERIMENTAL_SCREENSHOT_DIR, DIFF_SCREENSHOT_DIR):
            if directory.exists():
                shutil.rmtree(directory)
            directory.mkdir(parents=True, exist_ok=True)
            print(f"Cleared and recreated directory: {directory}")

    async def init_on_page(self, page, url):
        pass

    async def log(self, page, url, environment):
        location = url.split("//")[1].split("/", 1)[1]
        safe_url = location.replace('/', '_').replace('.', '_')
        await self.scroll_to_bottom(page)
        target_dir = CONTROL_SCREENSHOT_DIR if environment == "control" else EXPERIMENTAL_SCREENSHOT_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(target_dir / f"{safe_url}.png"), full_page=True)
        self.screenshot_count += 1
        print(f"Screenshot taken for {url} ({environment})")

    def write_logs(self):
        print(f"Total screenshots taken: {self.screenshot_count}")

    def get_screenshot_count(self):
        return self.screenshot_count

    async def scroll_to_bottom(self, page):
        dimensions = await page.evaluate("""() => {
            return {
                width: document.documentElement.scrollWidth,
                height: document.documentElement.scrollHeight,
                viewportHeight: window.innerHeight
            }
        }""")
        current_position = 0
        while current_position < dimensions['height']:
            await page.evaluate(f"window.scrollTo(0, {current_position})")
            await page.wait_for_timeout(50)
            current_position += dimensions['viewportHeight']
        await page.evaluate(f"window.scrollTo(0, {current_position})")
        await page.wait_for_timeout(50)
