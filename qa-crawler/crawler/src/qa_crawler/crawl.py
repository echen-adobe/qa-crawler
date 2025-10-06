"""Asynchronous crawler logic used by the CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

if __package__ is None or __package__ == "":  # pragma: no cover - script execution fallback
    repo_src = Path(__file__).resolve().parents[2] / "src"
    if str(repo_src) not in sys.path:
        sys.path.insert(0, str(repo_src))

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.async_api import async_playwright

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


def resolve_sitemap_sources(config: Mapping[str, Any]) -> list[str]:
    """Return unique sitemap URLs defined in the config (if any)."""

    sources: list[str] = []
    raw = config.get("sitemap_urls")
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, Iterable):
        for candidate in raw:
            if isinstance(candidate, str):
                trimmed = candidate.strip()
                if trimmed:
                    sources.append(trimmed)
    single = config.get("sitemap_url")
    if isinstance(single, str):
        trimmed = single.strip()
        if trimmed:
            sources.append(trimmed)

    unique_sources: list[str] = []
    seen: set[str] = set()
    for source in sources:
        if source in seen:
            continue
        seen.add(source)
        unique_sources.append(source)
    return unique_sources


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
    def is_supported(loc_value: str) -> bool:
        return loc_value.startswith("https://www.adobe.com/") and "/express/" in loc_value

    try:
        soup = BeautifulSoup(text, "xml")
        for loc in soup.find_all("loc"):
            loc_text = (loc.text or "").strip()
            print(loc_text)
            if is_supported(loc_text):
                urls.append(loc_text)
    except Exception:
        urls = []

    if not urls:
        urls = [
            match.strip()
            for match in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.IGNORECASE)
            if is_supported(match)
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


def _collect_manual_urls(
    config: Mapping[str, Any],
    sitemap_path: str | Path,
    seen: set[str],
) -> tuple[list[str], dict[str, str], str]:
    canonical_urls: list[str] = []
    url_origins: dict[str, str] = {}

    manual_label = f"manual entries from {Path(sitemap_path).name}"
    raw_urls = config.get("urls", [])
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    if isinstance(raw_urls, Iterable):
        for candidate in raw_urls:
            if not isinstance(candidate, str):
                continue
            trimmed = candidate.strip()
            if not trimmed or trimmed in seen:
                continue
            seen.add(trimmed)
            canonical_urls.append(trimmed)
            url_origins[trimmed] = manual_label

    return canonical_urls, url_origins, manual_label


async def _collect_sitemap_urls(
    context,
    config: Mapping[str, Any],
    sitemap_source: str,
    seen: set[str],
) -> tuple[list[str], dict[str, str]]:
    canonical_urls: list[str] = []
    url_origins: dict[str, str] = {}
    sitemap_results = await fetch_sitemap_urls(context, sitemap_source)
    for candidate in sitemap_results:
        if candidate in seen:
            continue
        seen.add(candidate)
        canonical_urls.append(candidate)
        url_origins[candidate] = sitemap_source
    return canonical_urls, url_origins


async def _build_environment_urls(
    config: Mapping[str, Any],
    canonical_urls: Iterable[str],
    url_origins: Mapping[str, str],
) -> tuple[list[str], list[str], dict[str, str]]:
    canonical_list = list(canonical_urls)
    control_urls = await get_urls_for_environment(canonical_list, config["control_branch_host"])
    experimental_urls = await get_urls_for_environment(canonical_list, config["experimental_branch_host"])

    url_to_sitemap: dict[str, str] = {}
    for base_url, control_url, experimental_url in zip(canonical_list, control_urls, experimental_urls):
        origin = url_origins.get(base_url)
        if origin is None:
            origin = "manual entries"
        url_to_sitemap[control_url] = origin
        url_to_sitemap[experimental_url] = origin

    return control_urls, experimental_urls, url_to_sitemap


async def get_urls(context, sitemap_file: str | Path) -> tuple[list[str], list[str], dict[str, str]]:
    config = await load_config(sitemap_file)
    seen: set[str] = set()
    manual_urls, manual_origins, manual_label = _collect_manual_urls(config, sitemap_file, seen)

    sitemap_sources = resolve_sitemap_sources(config)
    all_canonical = list(manual_urls)
    all_origins = dict(manual_origins)

    if sitemap_sources:
        for source in sitemap_sources:
            canonical_urls, url_origins = await _collect_sitemap_urls(context, config, source, seen)
            all_canonical.extend(canonical_urls)
            all_origins.update(url_origins)

    if not all_canonical and sitemap_sources:
        # If no canonical URLs were added (e.g., manual URLs filtered out), fall back to fetching all.
        for source in sitemap_sources:
            sitemap_results = await fetch_sitemap_urls(context, source)
            for candidate in sitemap_results:
                all_canonical.append(candidate)
                all_origins.setdefault(candidate, source)

    return await _build_environment_urls(config, all_canonical, all_origins)


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
    except Exception as exc:
        if "failure" in loggers:
            import traceback

            stack_trace = traceback.format_exc()
            await loggers["failure"].log(page, url, environment, error=exc, stack_trace=stack_trace)
    finally:
        await page.close()


async def run_crawl(
    sitemap_file: str | Path,
    *,
    batch_size: int = 10,
    limit: int = 5,
    new_version: bool = False,
) -> None:
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

        try:
            config = await load_config(sitemap_file)
            sitemap_sources = resolve_sitemap_sources(config)
            seen: set[str] = set()

            manual_urls, manual_origins, manual_label = _collect_manual_urls(
                config, sitemap_file, seen
            )

            url_groups: list[tuple[str, list[str], dict[str, str]]] = []
            if manual_urls:
                url_groups.append((manual_label, manual_urls, manual_origins))

            for source in sitemap_sources:
                canonical_urls, url_origins = await _collect_sitemap_urls(
                    control_context, config, source, seen
                )
                url_groups.append((source, canonical_urls, url_origins))

            if not url_groups:
                print("No URLs found in configuration; nothing to crawl.")
                return

            iteration_limit: int | None = limit if limit > 0 else None

            async def run_group(
                label: str,
                canonical_urls: list[str],
                url_origins: dict[str, str],
            ) -> None:

                if not canonical_urls:
                    print(f"No URLs discovered for {label}; skipping.")
                    return

                selected_canonical = canonical_urls
                if iteration_limit is not None:
                    selected_canonical = canonical_urls[:iteration_limit]

                control_urls, experimental_urls, url_to_sitemap = await _build_environment_urls(
                    config, selected_canonical, url_origins
                )

                if not control_urls:
                    print(f"No environment URLs generated for {label}; skipping.")
                    return

                loggers: dict[str, Logger] = {
                    "source": SourceLogger(new_version=new_version, url_to_sitemap=url_to_sitemap),
                    "failure": FailureLogger(),
                }
                if DomLogger:
                    loggers["dom"] = DomLogger()

                for logger in loggers.values():
                    if hasattr(logger, "initialize") and callable(logger.initialize):
                        await logger.initialize()  # type: ignore[attr-defined]

                total_urls = len(control_urls)
                print(f"Starting crawl for {label} ({total_urls} URLs)")

                for index in range(0, total_urls, batch_size):
                    control_batch = control_urls[index : index + batch_size]
                    experimental_batch = experimental_urls[index : index + batch_size]
                    control_tasks = [
                        process_page_with_context(control_context, url, "control", loggers)
                        for url in control_batch
                    ]
                    experimental_tasks = [
                        process_page_with_context(experimental_context, url, "experimental", loggers)
                        for url in experimental_batch
                    ]
                    await asyncio.gather(*(control_tasks + experimental_tasks))
                    print(
                        f"Completed batch {index // batch_size + 1} for {label}"
                    )
                    await asyncio.sleep(3)

                for logger in loggers.values():
                    if hasattr(logger, "write_logs_async") and callable(logger.write_logs_async):
                        await logger.write_logs_async()  # type: ignore[attr-defined]
                    else:
                        logger.write_logs()

                for logger in loggers.values():
                    cleanup_fn = getattr(logger, "cleanup", None)
                    if callable(cleanup_fn):
                        maybe_coro = cleanup_fn()
                        if asyncio.iscoroutine(maybe_coro):  # type: ignore[truthy-function]
                            await maybe_coro

                print(f"Finished crawl for {label}")
                return

            for label, canonical_urls, url_origins in url_groups:
                await run_group(label, canonical_urls, url_origins)
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
    parser.add_argument(
        "--new-version",
        action="store_true",
        help="Enable the new block map output structure",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    print(f"Starting crawler with sitemap: {args.sitemap}")
    asyncio.run(run_crawl(args.sitemap, new_version=args.new_version))
    return 0


__all__ = ["main", "run_crawl", "build_parser"]
main()
