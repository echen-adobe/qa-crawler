from .logger import Logger


class DomLogger(Logger):
    def __init__(self):
        super().__init__()
        self.screenshot_count = 0

    async def init_on_page(self, page, url):
        pass

    async def log(self, page, url, environment):
        location = url.split("//")[1].split("/", 1)[1]
        safe_url = location.replace('/', '_').replace('.', '_')
        cdp = await page.context().newCDPSession(page)
        snapshot = await cdp.send('DOMSnapshot.captureSnapshot', {
            'computedStyles': [
                'display', 'position', 'top', 'left',
                'width',   'height',  'margin', 'padding'
            ],
        })
        self.screenshot_count += 1
        print(f"Screenshot taken for {url} ({environment})")

    def write_logs(self):
        print(f"Total screenshots taken: {self.screenshot_count}")

    def get_screenshot_count(self):
        return self.screenshot_count

