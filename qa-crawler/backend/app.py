"""FastAPI service that exposes API-compatible block map search over CloudFront."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse


# Ensure the qa_crawler package (living under crawler/src) is importable.
REPO_ROOT = Path(__file__).resolve().parents[1]
CRAWLER_SRC = REPO_ROOT / "crawler" / "src"
if str(CRAWLER_SRC) not in sys.path:
    sys.path.insert(0, str(CRAWLER_SRC))

from qa_crawler.search import (  # noqa: E402  # isort:skip
    exact_match_urls,
    tokenize_query,
    top_similar_combinations,
    rewrite_branch_url,
    add_martech_off,
    unique_preserve_order,
)


# Load environment variables from repo-level .env (if present)
load_dotenv(REPO_ROOT / ".env")


def _normalize_keywords(raw: Optional[Iterable[str]]) -> List[str]:
    if raw is None:
        return []
    tokens: List[str] = []
    for item in raw:
        if item is None:
            continue
        stripped = str(item).strip()
        if stripped:
            tokens.append(stripped)
    return tokens


def _classify_locale(url: str) -> Optional[str]:
    """Return normalized locale key for the given index URL."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    segments = [seg.lower() for seg in parsed.path.split("/") if seg]
    if not segments:
        return None
    first = segments[0]
    if first == "express":
        return "default"
    return first


def _filter_index_by_locales(index: Dict[str, str], locales: Iterable[str]) -> Dict[str, str]:
    tokens = {
        str(loc).strip().lower()
        for loc in locales
        if loc is not None and str(loc).strip()
    }
    if not tokens:
        return index

    include_default = "default" in tokens
    tokens.discard("default")

    filtered: Dict[str, str] = {}
    for filename, source_url in index.items():
        locale = _classify_locale(source_url)
        if locale is None:
            if include_default:
                filtered[filename] = source_url
            continue
        if locale == "default":
            if include_default:
                filtered[filename] = source_url
            continue
        if locale in tokens:
            filtered[filename] = source_url

    return filtered


def _base_cloudfront_url() -> str:
    """Resolve the base CloudFront URL from environment variables."""
    explicit = os.getenv("CLOUDFRONT_BASE_URL") or os.getenv("CLOUDFRONT_URL")
    if explicit:
        return explicit.rstrip("/")

    domain = os.getenv("CLOUDFRONT_DOMAIN") or os.getenv("CLOUDFRONT_DISTRIBUTION")
    if domain:
        domain = domain.strip()
        if domain.startswith("http://") or domain.startswith("https://"):
            return domain.rstrip("/")
        return f"https://{domain.rstrip('/')}"

    # Fallback to the CloudFront distribution highlighted in the task instructions.
    return "https://d32kos99qfjxkz.cloudfront.net"


class CloudFrontBlockMapClient:
    """Fetches and caches block map shards from the CloudFront distribution."""

    INDEX_PATH = "all_domains/current/index.json"

    def __init__(
        self,
        base_url: str,
        *,
        index_ttl_seconds: int = 300,
        block_map_ttl_seconds: int = 1800,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._index_ttl = index_ttl_seconds
        self._block_ttl = block_map_ttl_seconds
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

        # Cache structures guarded by locks to avoid duplicate fetches.
        self._index_cache: Optional[Dict[str, str]] = None
        self._index_expiry: float = 0.0
        self._index_lock = asyncio.Lock()

        self._block_cache: Dict[str, tuple[Dict[str, Any], float]] = {}
        self._block_lock = asyncio.Lock()

    def _url_for(self, relative: str) -> str:
        return f"{self._base_url.rstrip('/')}/{relative.lstrip('/')}"

    async def close(self) -> None:
        await self._client.aclose()

    async def get_index(self) -> Dict[str, str]:
        async with self._index_lock:
            now = time.time()
            if self._index_cache is not None and now < self._index_expiry:
                return self._index_cache

            resp = await self._client.get(self._url_for(self.INDEX_PATH))
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=exc.response.status_code, detail="Unable to download index.json") from exc

            data = resp.json()
            if not isinstance(data, dict):
                raise HTTPException(status_code=502, detail="index.json payload malformed")

            self._index_cache = {str(k): str(v) for k, v in data.items()}
            self._index_expiry = now + self._index_ttl
            return self._index_cache

    async def get_block_map(self, filename: str) -> Dict[str, Any]:
        filename = filename.strip()
        if not filename:
            raise ValueError("Block map filename must be non-empty")

        now = time.time()
        cached = self._block_cache.get(filename)
        if cached and now < cached[1]:
            return cached[0]

        async with self._block_lock:
            cached = self._block_cache.get(filename)
            if cached and time.time() < cached[1]:
                return cached[0]

            url = self._url_for(f"all_domains/current/{filename}")
            resp = await self._client.get(url)
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise HTTPException(status_code=exc.response.status_code, detail=f"Unable to download block map '{filename}'") from exc

            data = resp.json()
            if not isinstance(data, dict):
                raise HTTPException(status_code=502, detail=f"Block map '{filename}' payload malformed")

            expiry = time.time() + self._block_ttl
            self._block_cache[filename] = (data, expiry)
            return data


@lru_cache(maxsize=1)
def get_client() -> CloudFrontBlockMapClient:
    base = _base_cloudfront_url()
    index_ttl = int(os.getenv("BLOCK_MAP_INDEX_TTL", "300"))
    block_ttl = int(os.getenv("BLOCK_MAP_SHARD_TTL", "1800"))
    timeout = float(os.getenv("BLOCK_MAP_HTTP_TIMEOUT", "10"))
    return CloudFrontBlockMapClient(
        base,
        index_ttl_seconds=index_ttl,
        block_map_ttl_seconds=block_ttl,
        timeout_seconds=timeout,
    )


app = FastAPI(title="QA Crawler Block Map Search", version="0.1.0")


@app.on_event("shutdown")
async def _shutdown_client() -> None:
    client = get_client()
    await client.close()


@app.get("/query-blocks")
async def query_blocks(
    keywords: Optional[List[str]] = Query(None, description="Keywords to search for across all block map shards"),
    branch: Optional[str] = Query(None, description="Optional branch to rewrite URLs before scoring"),
    locales: Optional[List[str]] = Query(None, description="Restrict search to locales (use 'default' for the primary US site)"),
    limit: Optional[int] = Query(None, ge=1, description="Limit the number of exact URLs returned per shard"),
    combo_limit: int = Query(5, ge=1, le=50, description="Number of similar class-name combinations to return per shard"),
    similarity_threshold: int = Query(80, ge=0, le=100, description="Minimum fuzz score required for similar combinations"),
    martech_off: Optional[bool] = Query(None, alias="append_martech_off", description="Force appending martech=off to rewritten URLs"),
) -> JSONResponse:
    keyword_list = _normalize_keywords(keywords)
    if not keyword_list:
        raise HTTPException(status_code=400, detail="At least one keyword must be supplied")

    query = " ".join(keyword_list)
    tokens = tokenize_query(query)

    client = get_client()
    index_data = await client.get_index()
    filtered_index = _filter_index_by_locales(index_data, locales or [])

    results: List[Dict[str, Any]] = []
    for filename, source_url in filtered_index.items():
        block_map = await client.get_block_map(filename)

        # Exact matches and combinations mirror the lambda_search implementation.
        exact_urls = exact_match_urls(block_map, tokens)

        if branch:
            rewritten = [rewrite_branch_url(u, branch) for u in exact_urls]
            append_off = martech_off if martech_off is not None else True
            if append_off:
                rewritten = [add_martech_off(u) for u in rewritten]
            exact_urls = unique_preserve_order(rewritten)

        if limit and limit > 0:
            exact_urls = exact_urls[:limit]

        combos = top_similar_combinations(block_map, query, top_k=combo_limit)
        top_combos = [
            {"combination": combo_str, "score": score, "hash_key": hash_key}
            for combo_str, score, hash_key in combos
            if int(score) >= similarity_threshold
        ]

        if exact_urls or top_combos:
            results.append(
                {
                    "block_map": filename,
                    "source_url": source_url,
                    "exact_urls": exact_urls,
                    "top_combinations": top_combos,
                }
            )

    payload = {
        "keywords": tokens,
        "result_count": len(results),
        "results": results,
    }
    return JSONResponse(content=payload)
