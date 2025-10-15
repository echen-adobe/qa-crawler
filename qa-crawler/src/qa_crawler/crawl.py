"""Asynchronous crawler logic used by the CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Iterable

if __package__ is None or __package__ == "":  # pragma: no cover - script execution fallback
    repo_src = Path(__file__).resolve().parents[2] / "src"
    if str(repo_src) not in sys.path:
        sys.path.insert(0, str(repo_src))

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from qa_crawler.config import (
    CONTROL_SCREENSHOT_DIR,
    DEFAULT_BLOCK_MAP,
    SITEMAPS_DIR,
    ensure_data_directories,
)
from qa_crawler.loggers import FailureLogger, Logger, SourceLogger

# Optional loggers are imported lazily to avoid heavyweight dependencies when unused.
try:  # pragma: no cover - optional tooling
    from qa_crawler.loggers import ScreenshotLogger, DomLogger  # type: ignore
except Exception:  # pragma: no cover - when Pillow/Playwright extras unavailable
    ScreenshotLogger = None  # type: ignore
    DomLogger = None  # type: ignore

load_dotenv()
print("Loaded environment variables")

async def load_config(sitemap_file: str | Path) -> dict[str, Any]:
    path = Path(sitemap_file)
    if not path.is_absolute():
        path = (SITEMAPS_DIR / path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


async def fetch_sitemap_urls(context, sitemap_url: str, timeout_ms: int = 60_000) -> list[str]:
    try:
        response = await context.request.get(sitemap_url, timeout=timeout_ms)
        if not response.ok:
            raise RuntimeError(f"Sitemap request failed with status {response.status}")
        text = await response.text()
    except Exception as exc:  # pragma: no cover - network errors surfaced to console
        print(f"Failed to fetch sitemap {sitemap_url}: {exc}")
        return []

    urls: list[str] = []
    try:
        soup = BeautifulSoup(text, "xml")
        for loc in soup.find_all("loc"):
            loc_text = (loc.text or "").strip()
            if loc_text.startswith("https://www.adobe.com/express/"):
                urls.append(loc_text)
    except Exception:
        urls = []

    if not urls:
        urls = [
            match.strip()
            for match in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.IGNORECASE)
            if match.startswith("https://www.adobe.com/express/")
        ]

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in urls:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


async def get_urls_for_environment(urls: Iterable[str], environment: str) -> list[str]:
    environment_urls: list[str] = []
    for url in urls:
        if url.startswith("/"):
            environment_urls.append(environment + url)
        else:
            location = url.split("//", 1)[1].split("/", 1)[1]
            environment_urls.append(environment + "/" + location)
    return environment_urls


async def get_urls(context, sitemap_file: str | Path) -> tuple[list[str], list[str]]:
    config = await load_config(sitemap_file)
    urls = config.get("urls", [])
    if not urls:
        urls = await fetch_sitemap_urls(context, config["sitemap_url"])
    control_urls = await get_urls_for_environment(urls, config["control_branch_host"])
    experimental_urls = await get_urls_for_environment(urls, config["experimental_branch_host"])
    return control_urls, experimental_urls


async def process_page_with_context(context, url: str, environment: str, loggers: dict[str, Logger]):
    page = await context.new_page()
    await page.evaluate("document.documentElement.style.setProperty('--animation-speed', '0s')")
    await page.evaluate("document.documentElement.style.setProperty('transition', 'none')")
    await asyncio.sleep(random.randint(1, 5) / 10.0)

    try:
        for logger in loggers.values():
            await logger.init_on_page(page, url)

        try:
            from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

            parsed = urlparse(url)
            query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query_items["martech"] = "off"
            new_query = urlencode(query_items, doseq=True)
            nav_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        except Exception:
            nav_url = url + ("&martech=off" if ("?" in url) else "?martech=off")

        await page.goto(nav_url, wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(random.randint(1, 5)) 
        await page.wait_for_selector("body", state="attached", timeout=45000)
        await page.wait_for_function("""
        () => {
            const b = document.body;
            const s = b && getComputedStyle(b);
            return s && s.visibility !== 'hidden' && s.display !== 'none';
        }
        """, timeout=15000)

        for logger in loggers.values():
            await logger.log(page, url, environment)
    except PlaywrightTimeoutError as exc:
        if "failure" in loggers:
            await loggers["failure"].log(
                page,
                url,
                environment,
                error=f"Timeout waiting for page readiness: {exc}",
            )
    except Exception as exc:
        if "failure" in loggers:
            import traceback

            stack_trace = traceback.format_exc()
            await loggers["failure"].log(page, url, environment, error=exc, stack_trace=stack_trace)
    finally:
        await page.close()


async def run_crawl(sitemap_file: str | Path, *, batch_size: int = 10, limit: int = -1) -> None:
    ensure_data_directories()
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-http2",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
                "--start-maximized",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-web-security",
                "--disable-site-isolation-trials",
                "--no-sandbox",
                "--ignore-certificate-errors",
                "--ignore-certificate-errors-spki-list",
                "--enable-features=NetworkService,NetworkServiceInProcess",
            ],
        )

        context_options = {
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "viewport": {"width": 1920, "height": 1080},
            "extra_http_headers": {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                "Sec-Ch-Ua-Platform": '"macOS"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
            "bypass_csp": True,
            "ignore_https_errors": True,
            "service_workers": "block",
        }

        control_context = await browser.new_context(**context_options)
        experimental_context = await browser.new_context(**context_options)

        control_urls, experimental_urls = await get_urls(control_context, sitemap_file)
        total_urls = min(limit, len(control_urls)) if limit > 0 else len(control_urls)

        loggers: dict[str, Logger] = {
            "source": SourceLogger(),
            "failure": FailureLogger(),
        }
        if DomLogger:
            loggers["dom"] = DomLogger()

        for logger in loggers.values():
            if hasattr(logger, "initialize") and callable(logger.initialize):
                await logger.initialize()  # type: ignore[attr-defined]

        try:
            for index in range(0, total_urls, batch_size):
                control_batch = control_urls[index : index + batch_size]
                experimental_batch = experimental_urls[index : index + batch_size]
                control_tasks = [process_page_with_context(control_context, url, "control", loggers) for url in control_batch]
                experimental_tasks = [
                    process_page_with_context(experimental_context, url, "experimental", loggers)
                    for url in experimental_batch
                ]
                await asyncio.gather(*(control_tasks + experimental_tasks))
                print(f"Completed batch {index // batch_size + 1}")
                await asyncio.sleep(3)

            for logger in loggers.values():
                if hasattr(logger, "write_logs_async") and callable(logger.write_logs_async):
                    await logger.write_logs_async()  # type: ignore[attr-defined]
                else:
                    logger.write_logs()

            for logger in loggers.values():
                if hasattr(logger, "cleanup") and callable(logger.cleanup):
                    await logger.cleanup()  # type: ignore[attr-defined]
        finally:
            await control_context.close()
            await experimental_context.close()
            await browser.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Web crawler for QA testing")
    parser.add_argument(
        "--sitemap",
        type=str,
        default=str(SITEMAPS_DIR / "default_sitemap.json"),
        help="Path to the sitemap configuration file",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    print(f"Starting crawler with sitemap: {args.sitemap}")
    asyncio.run(run_crawl(args.sitemap))
    return 0


__all__ = ["main", "run_crawl", "build_parser"]
main()
