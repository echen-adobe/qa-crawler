import os
import shutil
from .logger import Logger


class ScreenshotLogger(Logger):
    def __init__(self):
        super().__init__()
        self.screenshot_count = 0
        self._clear_screenshot_directories()

    def _clear_screenshot_directories(self):
        directories = ['./qa/control', './qa/experimental', './qa/diff']
        for dir_path in directories:
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path)
            os.makedirs(dir_path, exist_ok=True)
            print(f"Cleared and recreated directory: {dir_path}")

    async def init_on_page(self, page, url):
        pass

    async def log(self, page, url, environment):
        location = url.split("//")[1].split("/", 1)[1]
        safe_url = location.replace('/', '_').replace('.', '_')
        await self.scroll_to_bottom(page)
        await page.screenshot(path=f"./qa/{environment}/{safe_url}.png", full_page=True)
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

