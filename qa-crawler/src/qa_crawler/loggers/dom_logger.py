"""Capture DOM snapshots via the Playwright CDP API."""

from __future__ import annotations

from .logger import Logger


class DomLogger(Logger):
    def __init__(self) -> None:
        super().__init__()
        self.snapshot_count = 0

    async def init_on_page(self, page, url):  # pragma: no cover - hook required by interface
        return None

    async def log(self, page, url, environment):
        context = page.context
        cdp = await context.new_cdp_session(page)
        await cdp.send(
            "DOMSnapshot.captureSnapshot",
            {
                "computedStyles": [
                    "display",
                    "position",
                    "top",
                    "left",
                    "width",
                    "height",
                    "margin",
                    "padding",
                ]
            },
        )
        self.snapshot_count += 1
        print(f"DOM snapshot captured for {url} ({environment})")

    def write_logs(self) -> None:
        print(f"Total DOM snapshots captured: {self.snapshot_count}")

    def get_snapshot_count(self) -> int:
        return self.snapshot_count
