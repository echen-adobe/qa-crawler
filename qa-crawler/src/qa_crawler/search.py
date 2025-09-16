#!/usr/bin/env python3
import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Set, Optional

from rapidfuzz import process, fuzz

from .config import REPO_ROOT


def load_block_map(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_corpus(block_map: Dict[str, Any]) -> List[str]:
    corpus: List[str] = []
    for hash_key, data in block_map.items():
        class_names = data.get("class_names", []) or []
        urls = data.get("urls", []) or []
        text = " ".join([hash_key, " ".join(class_names), " ".join(urls[:5])])
        corpus.append(text)
    return corpus


def tokenize_query(query: str) -> List[str]:
    return [t.strip().lower() for t in query.split() if t.strip()]


def exact_match_urls(block_map: Dict[str, Any], tokens: List[str]) -> List[str]:
    if not tokens:
        return []
    exact_urls: List[str] = []
    seen: Set[str] = set()
    for _hash_key, data in block_map.items():
        class_names = [c.lower() for c in (data.get("class_names", []) or [])]
        class_set = set(class_names)
        if all(t in class_set for t in tokens):
            for u in data.get("urls", []) or []:
                if u not in seen:
                    seen.add(u)
                    exact_urls.append(u)
    return exact_urls


def top_similar_combinations(block_map: Dict[str, Any], query: str, top_k: int = 5) -> List[Tuple[str, int, str]]:
    combos: List[str] = []
    keys: List[str] = []
    seen_combo: Set[str] = set()
    for hash_key, data in block_map.items():
        classes = [c.strip().lower() for c in (data.get("class_names", []) or []) if c and c.strip()]
        combo = " ".join(sorted(classes))
        if not combo:
            continue
        if combo in seen_combo:
            continue
        seen_combo.add(combo)
        combos.append(combo)
        keys.append(hash_key)
    if not combos or not query.strip():
        return []
    results = process.extract(query.strip().lower(), combos, scorer=fuzz.token_set_ratio, limit=top_k)
    output: List[Tuple[str, int, str]] = []
    for combo_str, score, idx in results:
        output.append((combo_str, int(score), keys[idx]))
    return output


def resolve_block_map_path(date: Optional[str], explicit_path: Optional[str]) -> str:
    if explicit_path:
        return explicit_path
    output_dir = REPO_ROOT / "output"
    candidate: Optional[Path] = None
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    if date:
        candidate = output_dir / date / "block_map.json"
        if not candidate.exists():
            candidate = None
    if candidate is None and output_dir.exists():
        dated_dirs = [p for p in output_dir.iterdir() if p.is_dir() and date_pattern.match(p.name)]
        dated_dirs.sort(key=lambda p: p.name, reverse=True)
        for d in dated_dirs:
            bm = d / "block_map.json"
            if bm.exists():
                candidate = bm
                break
    if candidate is None:
        candidate = REPO_ROOT / "backend" / "qa" / "block_map.json"
    return str(candidate)


def main() -> int:
    parser = argparse.ArgumentParser(description="Segmented search: URLs with exact keyword match and top similar class-name combinations")
    parser.add_argument("query", help="Keyword(s) to search for; space-separated tokens")
    parser.add_argument("--date", default=None, help="Date folder under output (YYYY-MM-DD). If omitted, uses most recent date.")
    parser.add_argument("--path", default=None, help="Explicit path to block_map.json (overrides --date)")
    parser.add_argument("--limit", type=int, default=10, help="Max URLs to print for exact matches")
    args = parser.parse_args()

    resolved_path = resolve_block_map_path(args.date, args.path)
    block_map = load_block_map(resolved_path)
    tokens = tokenize_query(args.query)

    exact_urls = exact_match_urls(block_map, tokens)
    if args.limit > 0:
        exact_urls = exact_urls[: args.limit]

    combos = top_similar_combinations(block_map, args.query, top_k=5)

    print("Exact match (all keywords):")
    if not exact_urls:
        print("(none)")
    else:
        for u in exact_urls:
            print(u)

    print("\nTop 5 similar class name combinations (combo, score):")
    if not combos:
        print("(none)")
    else:
        for combo_str, s, _h in combos:
            print(f"{combo_str} ({s})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

