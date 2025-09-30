import json
from typing import Any

from .logger import Logger
from qa_crawler.config import FAILED_URLS_PATH, ensure_data_directories


class FailureLogger(Logger):
    def __init__(self) -> None:
        super().__init__()
        self.failed_urls: list[dict[str, Any]] = []
        ensure_data_directories()

    async def init_on_page(self, page, url) -> None:  # pragma: no cover - interface hook
        return None

    async def log(self, page, url, environment, error=None, stack_trace=None) -> None:
        if not error:
            return
        self.failed_urls.append({
            "url": url,
            "environment": environment,
            "error": str(error),
            "stack_trace": stack_trace,
        })
        print(f"Failed to process {url}: {error}")
        if stack_trace:
            print(stack_trace)

    def write_logs(self) -> None:
        try:
            existing_failed_urls = json.loads(FAILED_URLS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            existing_failed_urls = []

        existing_combinations = {
            (item.get("url"), item.get("environment"))
            for item in existing_failed_urls
        }

        for new_failure in self.failed_urls:
            combo = (new_failure.get("url"), new_failure.get("environment"))
            if combo not in existing_combinations:
                existing_failed_urls.append(new_failure)

        FAILED_URLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        FAILED_URLS_PATH.write_text(json.dumps(existing_failed_urls, indent=2), encoding="utf-8")
        print(f"Failed URLs saved to {FAILED_URLS_PATH} (merged {len(self.failed_urls)} new failures)")
        print(f"Total failures: {len(existing_failed_urls)}")

    def get_failure_count(self) -> int:
        return len(self.failed_urls)
