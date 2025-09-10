# twitter_crawler.py
import asyncio, json, os, time, argparse
import re
from pathlib import Path
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from playwright.async_api import async_playwright
from loggers.screenshot_logger import ScreenshotLogger
from loggers.source_logger import SourceLogger
from loggers.failure_logger import FailureLogger
from loggers.logger import Logger
from loggers.dom_logger import DomLogger
import random

load_dotenv()

# Replace the hardcoded SITE_MAP with config loading
async def load_config(sitemap_file):
    with open(sitemap_file, 'r') as f:
        config = json.load(f)
    return config

async def fetch_sitemap_urls(context, sitemap_url, timeout_ms: int = 60000):
    try:
        response = await context.request.get(sitemap_url, timeout=timeout_ms)
        if not response.ok:
            raise RuntimeError(f"Sitemap request failed with status {response.status}")
        text = await response.text()

        # Primary: XML parse via BeautifulSoup
        urls: list[str] = []
        try:
            soup = BeautifulSoup(text, 'xml')
            for loc in soup.find_all('loc'):
                loc_text = (loc.text or '').strip()
                if loc_text.startswith("https://www.adobe.com/express/"):
                    urls.append(loc_text)
        except Exception:
            urls = []

        # Fallback: regex parse of <loc> tags
        if not urls:
            urls = [m.strip() for m in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.IGNORECASE)]
            urls = [u for u in urls if u.startswith("https://www.adobe.com/express/")]

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)
        return deduped
    except Exception as e:
        print(f"Failed to fetch sitemap {sitemap_url}: {e}")
        return []

async def get_urls(context, sitemap_file):
    config = await load_config(sitemap_file)
    urls = config['urls']
    control_urls = []
    experimental_urls = []
    if len(config['urls']) == 0:
        # If urls array is empty, fetch from sitemap via request API to avoid navigation timeouts
        urls = await fetch_sitemap_urls(context, config['sitemap_url'])
    return await get_urls_for_environment(urls, config['control_branch_host']), await get_urls_for_environment(urls, config['experimental_branch_host'])

async def get_urls_for_environment(urls, environment):
    environment_urls = []
    for url in urls:
        if url.startswith("/"):
            environment_urls.append(environment + url)
        else:
            location = url.split("//")[1].split("/",1)[1]
            environment_urls.append(environment + "/" + location)
    return environment_urls

async def process_page_with_context(context, url, environment, loggers: dict[str, Logger]):
    page = await context.new_page()
    await page.evaluate("document.documentElement.style.setProperty('--animation-speed', '0s')")
    await page.evaluate("document.documentElement.style.setProperty('transition', 'none')")
    await asyncio.sleep(random.randint(1, 5) / 10.0)
    try:
        # await page.set_viewport_size({"width": 1920, "height": 1080})
        
        # Initialize all loggers for this page
        for logger in loggers.values():
            await logger.init_on_page(page, url)
        
        # Append or force martech=off to reduce third-party marketing scripts
        try:
            parsed = urlparse(url)
            query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query_items['martech'] = 'off'
            new_query = urlencode(query_items, doseq=True)
            nav_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        except Exception:
            nav_url = url + ("&martech=off" if ("?" in url) else "?martech=off")

        await page.goto(nav_url, wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(random.randint(1, 5))
        # Add a small delay to allow initial page load
       
        
        await page.wait_for_selector('body', timeout=15000)
        #await page.wait_for_load_state("load")
        # Log data for this page with all loggers
        for logger in loggers.values():
            await logger.log(page, url, environment)
            
    except Exception as e:
        # On error, only call failure logger
        if 'failure' in loggers:
            import traceback
            stack_trace = traceback.format_exc()
            await loggers['failure'].log(page, url, environment, error=e, stack_trace=stack_trace)
    finally:
        await page.close()

async def main(sitemap_file):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--disable-http2',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--window-size=1920,1080',
                '--start-maximized',
                '--disable-features=IsolateOrigins,site-per-process', # Disable site isolation
                '--disable-web-security',  # Disable CORS and other security features
                '--disable-site-isolation-trials',
                '--no-sandbox',
                '--ignore-certificate-errors',
                '--ignore-certificate-errors-spki-list',
                '--enable-features=NetworkService,NetworkServiceInProcess'
            ]
        )
        
        # Default user agent and headers for both contexts
        context_options = {
            'user_agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'viewport': {'width': 1920, 'height': 1080},
            'extra_http_headers': {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
                'Sec-Ch-Ua-Platform': '"macOS"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1'
            },
            'bypass_csp': True,  # Bypass Content Security Policy
            'ignore_https_errors': True,  # Ignore HTTPS errors
            'service_workers': 'block'
        }
            
        # Create two persistent contexts - one for control and one for experimental
        control_context = await browser.new_context(**context_options)
        experimental_context = await browser.new_context(**context_options)
        
        control_urls, experimental_urls = await get_urls(control_context, sitemap_file)
        limit = -1
        batch_size = 10
        
        # Initialize loggers
        loggers = {
            # 'screenshot': ScreenshotLogger(),
            # 'dom': DomLogger(),
            "source": SourceLogger(),
            'failure': FailureLogger()
        }
        
        # Initialize all loggers
        for logger in loggers.values():
            if hasattr(logger, 'initialize') and callable(logger.initialize):
                await logger.initialize()
        
        try:
            total_urls = min(limit, len(control_urls)) if limit > 0 else len(control_urls)
            for i in range(0, total_urls, batch_size):
                control_batch = control_urls[i:i + batch_size]
                experimental_batch = experimental_urls[i:i + batch_size]
                control_tasks = [
                    process_page_with_context(control_context, url, 'control', loggers) 
                    for url in control_batch
                ]
                experimental_tasks = [
                    process_page_with_context(experimental_context, url, 'experimental', loggers) 
                    for url in experimental_batch
                ]
                await asyncio.gather(*(control_tasks + experimental_tasks))
                print(f"Completed batch {i//batch_size + 1}")
                await asyncio.sleep(3)
            
            # Write all logs at the end
            for logger in loggers.values():
                if hasattr(logger, 'write_logs_async') and callable(logger.write_logs_async):
                    await logger.write_logs_async()
                else:
                    logger.write_logs()
                    
            # Cleanup loggers
            for logger in loggers.values():
                if hasattr(logger, 'cleanup') and callable(logger.cleanup):
                    await logger.cleanup()
        finally:
            # Clean up browser contexts
            await control_context.close()
            await experimental_context.close()
            await browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Web crawler for QA testing')
    parser.add_argument('--sitemap', type=str, default='./sitemaps/default_sitemap.json',
                      help='Path to the sitemap configuration file (default: default_sitemap.json)')
    
    args = parser.parse_args()
    
    if args.sitemap != 'default_sitemap.json':
        print(f"Using sitemap file: {args.sitemap}")
    else:
        print("Using default sitemap file: default_sitemap.json")
    
    print("Starting crawler...")
    asyncio.run(main(args.sitemap))
