from backend.crawl import main as _legacy_main
import importlib
import argparse


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--sitemap", type=str, default="./sitemaps/default_sitemap.json")
    args, _ = parser.parse_known_args()
    # Prefer packaged crawler if migrated; fallback to legacy backend.crawl
    try:
        _pkg = importlib.import_module("qa_crawler.crawl")
        _main = getattr(_pkg, "main")
    except Exception:
        _main = _legacy_main
    import asyncio
    asyncio.run(_main(args.sitemap))
    return 0

