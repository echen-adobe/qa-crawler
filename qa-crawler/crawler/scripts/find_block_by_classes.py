"""Locate block-map entries by class-name combination."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_block_map(map_path: Path) -> Dict[str, Dict[str, Any]]:
    with map_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize_classes(raw_classes: List[str]) -> List[str]:
    joined = " ".join(raw_classes)
    candidates = [token.strip().lower() for token in joined.replace(",", " ").split() if token.strip()]
    seen: set[str] = set()
    result: List[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result


def jaccard_similarity(a: List[str], b: List[str]) -> float:
    set_a = set(a)
    set_b = set(b)
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def find_exact_match(query_classes: List[str], block_map: Dict[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    query_set = set(query_classes)
    for entry_id, entry in block_map.items():
        entry_classes = [c.strip().lower() for c in entry.get("class_names", [])]
        if set(entry_classes) == query_set:
            return entry_id, entry
    return "", {}


def rank_close_matches(query_classes: List[str], block_map: Dict[str, Dict[str, Any]], top_k: int = 5) -> List[Tuple[str, float, Dict[str, Any]]]:
    query_norm = [c.strip().lower() for c in query_classes]
    candidates: List[Tuple[str, float, Dict[str, Any]]] = []
    q_len = len(set(query_norm))

    for entry_id, entry in block_map.items():
        entry_classes = [c.strip().lower() for c in entry.get("class_names", [])]
        score = jaccard_similarity(query_norm, entry_classes)
        if score <= 0.0:
            continue
        candidates.append((entry_id, score, entry))

    candidates.sort(
        key=lambda item: (
            item[1],
            -abs(len(set(item[2].get("class_names", []))) - q_len),
            -len(item[2].get("class_names", [])),
            item[0],
        ),
        reverse=True,
    )
    return candidates[:top_k]


def default_map_path() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "data" / "qa" / "block_map.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find entries in block_map.json by class name combination.")
    parser.add_argument(
        "classes",
        nargs="+",
        help="Class names to search (space- or comma-separated). Example: ax-columns fullsize width-2-columns",
    )
    parser.add_argument(
        "--map-file",
        dest="map_file",
        default=str(default_map_path()),
        help="Path to block_map.json (defaults to data/qa/block_map.json)",
    )
    parser.add_argument(
        "-k",
        "--top-k",
        dest="top_k",
        type=int,
        default=5,
        help="Number of close matches to return if no exact match (default: 5)",
    )
    parser.add_argument(
        "--output-json",
        dest="output_json",
        action="store_true",
        help="Output result as JSON",
    )
    return parser


def main(argv: List[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    map_path = Path(args.map_file)
    if not map_path.is_file():
        print(f"Error: map file not found: {map_path}", file=sys.stderr)
        return 2

    query_classes = normalize_classes(args.classes)
    if not query_classes:
        print("Error: No class names provided after normalization.", file=sys.stderr)
        return 2

    try:
        block_map = load_block_map(map_path)
    except Exception as exc:  # pragma: no cover - surface parse failures
        print(f"Error: failed to load map file: {exc}", file=sys.stderr)
        return 2

    entry_id, entry = find_exact_match(query_classes, block_map)
    if entry_id:
        if args.output_json:
            print(
                json.dumps(
                    {
                        "exact_match": {
                            "id": entry_id,
                            "class_names": entry.get("class_names", []),
                            "urls": entry.get("urls", []),
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print("Exact match found:\n")
            print(f"id: {entry_id}")
            print(f"class_names: {entry.get('class_names', [])}")
            urls = entry.get("urls", [])
            print(f"urls ({len(urls)}):")
            for url in urls:
                print(f"  - {url}")
        return 0

    matches = rank_close_matches(query_classes, block_map, top_k=args.top_k)
    if args.output_json:
        print(
            json.dumps(
                {
                    "exact_match": None,
                    "matches": [
                        {
                            "id": match_id,
                            "score": round(score, 4),
                            "class_names": match_entry.get("class_names", []),
                            "urls": match_entry.get("urls", []),
                        }
                        for (match_id, score, match_entry) in matches
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("No exact match found. Top candidates:\n")
        for rank, (match_id, score, match_entry) in enumerate(matches, start=1):
            print(f"{rank}. id: {match_id}")
            print(f"   score: {score:.4f}")
            print(f"   class_names: {match_entry.get('class_names', [])}")
            urls = match_entry.get("urls", [])
            preview = urls[:3]
            print(f"   urls: {len(urls)} total")
            for url in preview:
                print(f"     - {url}")
            if len(urls) > len(preview):
                print("     - ...")
    return 0


if __name__ == "__main__":  # pragma: no cover - manual invocation
    sys.exit(main(sys.argv[1:]))
