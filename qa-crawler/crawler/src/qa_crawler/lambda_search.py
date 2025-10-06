"""Lambda-style handlers wrapping the search logic for QA crawler block maps."""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List
from pathlib import Path

from qa_crawler.search import (
    load_block_map,
    tokenize_query,
    exact_match_urls,
    top_similar_combinations,
    rewrite_branch_url,
    add_martech_off,
    unique_preserve_order,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CURRENT_DIR = REPO_ROOT / "current"


def _current_dir() -> Path:
    override = os.getenv("QA_CRAWLER_CURRENT_DIR")
    return Path(override) if override else DEFAULT_CURRENT_DIR


def _index_path() -> Path:
    override = os.getenv("QA_CRAWLER_INDEX_PATH")
    return Path(override) if override else _current_dir() / "index.json"


def _normalize_keywords(raw_keywords: Any) -> List[str]:
    if raw_keywords is None:
        return []
    if isinstance(raw_keywords, str):
        raw_keywords = [raw_keywords]
    elif isinstance(raw_keywords, Iterable):
        raw_keywords = list(raw_keywords)
    else:
        raise TypeError("keywords must be a string or iterable of strings")
    tokens = [str(k).strip() for k in raw_keywords if str(k).strip()]
    return tokens


def block_map_search_handler(event: Dict[str, Any], _context: Any = None) -> Dict[str, Any]:
    keywords = _normalize_keywords(event.get("keywords"))
    block_map_filename = event.get("block_map_filename")
    if not block_map_filename:
        raise ValueError("block_map_filename is required")

    block_map_path = _current_dir() / block_map_filename
    if not block_map_path.exists():
        raise FileNotFoundError(f"Block map file '{block_map_filename}' not found under {_current_dir()}")

    block_map = load_block_map(str(block_map_path))
    query = " ".join(keywords)
    tokens = tokenize_query(query)

    exact_urls = exact_match_urls(block_map, tokens)

    branch = event.get("branch")
    append_martech_off = event.get("append_martech_off", bool(branch))
    if branch:
        rewritten = [rewrite_branch_url(u, branch) for u in exact_urls]
        if append_martech_off:
            rewritten = [add_martech_off(u) for u in rewritten]
        exact_urls = unique_preserve_order(rewritten)

    limit = event.get("limit")
    if isinstance(limit, int) and limit > 0:
        exact_urls = exact_urls[:limit]

    combo_limit = event.get("combo_limit", 5)
    combos = top_similar_combinations(block_map, query, top_k=combo_limit)
    top_combinations = [
        {"combination": combo_str, "score": score, "hash_key": hash_key}
        for combo_str, score, hash_key in combos
    ]

    return {
        "block_map": block_map_filename,
        "keywords": tokens,
        "exact_urls": exact_urls,
        "top_combinations": top_combinations,
    }


def aggregate_search_handler(event: Dict[str, Any], _context: Any = None) -> Dict[str, Any]:
    keywords = _normalize_keywords(event.get("keywords"))

    index_path = _index_path()
    if not index_path.exists():
        raise FileNotFoundError(f"index.json not found at {index_path}")

    with open(index_path, "r", encoding="utf-8") as handle:
        index_data: Dict[str, str] = json.load(handle)

    include_empty = event.get("include_empty", False)

    results: List[Dict[str, Any]] = []
    for block_map_filename, source_url in index_data.items():
        sub_event = {
            "keywords": keywords,
            "block_map_filename": block_map_filename,
        }
        for key in ("branch", "limit", "combo_limit", "append_martech_off"):
            if key in event:
                sub_event[key] = event[key]
        block_result = block_map_search_handler(sub_event)
        if include_empty or block_result["exact_urls"] or block_result["top_combinations"]:
            block_result["source_url"] = source_url
            results.append(block_result)

    return {
        "keywords": tokenize_query(" ".join(keywords)) if keywords else [],
        "results": results,
    }
