import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from qa_crawler.crawl import resolve_sitemap_sources  # noqa: E402


def test_resolve_sitemap_sources_deduplicates_and_trims():
    config = {
        "sitemap_urls": [
            " https://example.com/a.xml ",
            "https://example.com/b.xml",
            "https://example.com/a.xml",
        ],
        "sitemap_url": "https://example.com/b.xml",
    }

    result = resolve_sitemap_sources(config)

    assert result == [
        "https://example.com/a.xml",
        "https://example.com/b.xml",
    ]


def test_resolve_sitemap_sources_accepts_string():
    config = {"sitemap_urls": "https://example.com/sitemap.xml"}
    assert resolve_sitemap_sources(config) == ["https://example.com/sitemap.xml"]


@pytest.mark.parametrize("config", [{}, {"sitemap_urls": []}, {"sitemap_url": ""}])
def test_resolve_sitemap_sources_empty(config):
    assert resolve_sitemap_sources(config) == []
