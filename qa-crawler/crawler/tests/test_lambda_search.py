import json
import sys
from pathlib import Path

import pytest


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from qa_crawler.lambda_search import (  # noqa: E402
    block_map_search_handler,
    aggregate_search_handler,
)


@pytest.fixture
def temp_block_map(tmp_path):
    current_dir = tmp_path / "current"
    current_dir.mkdir()
    block_map = {
        "hash1": {
            "class_names": ["hero", "centered"],
            "urls": ["https://example.com/hero"],
        },
        "hash2": {
            "class_names": ["footer", "wide"],
            "urls": ["https://example.com/footer"],
        },
    }
    filename = "block-map-test.json"
    (current_dir / filename).write_text(json.dumps(block_map), encoding="utf-8")
    return current_dir, filename


def test_block_map_search_handler_exact_match(temp_block_map, monkeypatch):
    current_dir, filename = temp_block_map
    monkeypatch.setenv("QA_CRAWLER_CURRENT_DIR", str(current_dir))

    event = {"keywords": ["hero", "centered"], "block_map_filename": filename}
    result = block_map_search_handler(event)

    assert result["block_map"] == filename
    assert result["keywords"] == ["hero", "centered"]
    assert "https://example.com/hero" in result["exact_urls"]
    assert isinstance(result["top_combinations"], list)


def test_aggregate_search_handler_filters_empty(temp_block_map, tmp_path, monkeypatch):
    current_dir, filename = temp_block_map
    index_path = tmp_path / "index.json"
    index_payload = {filename: "https://example.com/sitemap.xml"}
    index_path.write_text(json.dumps(index_payload), encoding="utf-8")

    monkeypatch.setenv("QA_CRAWLER_CURRENT_DIR", str(current_dir))
    monkeypatch.setenv("QA_CRAWLER_INDEX_PATH", str(index_path))

    result = aggregate_search_handler({"keywords": ["hero"]})

    assert result["keywords"] == ["hero"]
    assert result["results"], "Expected at least one result entry"
    block_result = result["results"][0]
    assert block_result["block_map"] == filename
    assert block_result["source_url"] == index_payload[filename]
    assert block_result["exact_urls"]
