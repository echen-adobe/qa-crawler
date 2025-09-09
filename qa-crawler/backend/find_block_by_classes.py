import argparse
import json
import os
import sys
from typing import Dict, List, Tuple, Any


def load_block_map(map_path: str) -> Dict[str, Dict[str, Any]]:
	"""Load the block map JSON from the provided path."""
	with open(map_path, "r", encoding="utf-8") as f:
		return json.load(f)


def normalize_classes(raw_classes: List[str]) -> List[str]:
	"""Normalize user-provided class names: split on commas/whitespace, strip, lowercase, dedupe preserving order."""
	joined = " ".join(raw_classes)
	# Replace commas with spaces, then split
	candidates = [token.strip().lower() for token in joined.replace(",", " ").split() if token.strip()]
	seen = set()
	result: List[str] = []
	for c in candidates:
		if c not in seen:
			seen.add(c)
			result.append(c)
	return result


def jaccard_similarity(a: List[str], b: List[str]) -> float:
	"""Compute Jaccard similarity between two class name lists (treated as sets)."""
	set_a = set(a)
	set_b = set(b)
	if not set_a and not set_b:
		return 1.0
	intersection = len(set_a & set_b)
	union = len(set_a | set_b)
	return intersection / union if union else 0.0


def find_exact_match(query_classes: List[str], block_map: Dict[str, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
	"""Return (id, entry) if any entry has class_names set equal to query_classes set, else ("", {})."""
	query_set = set(query_classes)
	for entry_id, entry in block_map.items():
		entry_classes = [c.strip().lower() for c in entry.get("class_names", [])]
		if set(entry_classes) == query_set:
			return entry_id, entry
	return "", {}


def rank_close_matches(query_classes: List[str], block_map: Dict[str, Dict[str, Any]], top_k: int = 5) -> List[Tuple[str, float, Dict[str, Any]]]:
	"""Rank entries by Jaccard similarity and return top_k as (id, score, entry)."""
	query_norm = [c.strip().lower() for c in query_classes]
	candidates: List[Tuple[str, float, Dict[str, Any]]] = []
	for entry_id, entry in block_map.items():
		entry_classes = [c.strip().lower() for c in entry.get("class_names", [])]
		score = jaccard_similarity(query_norm, entry_classes)
		# Skip zero-similarity candidates
		if score <= 0.0:
			continue
		candidates.append((entry_id, score, entry))
	# Sort by score desc, then by smaller class set size difference, then by id for stability
	q_len = len(set(query_norm))
	candidates.sort(key=lambda x: (x[1], -abs(len(set(x[2].get("class_names", []))) - q_len), -len(x[2].get("class_names", [])), x[0]), reverse=True)
	return candidates[: top_k]


def default_map_path() -> str:
	# Resolve to qa/block_map.json next to this script
	script_dir = os.path.dirname(os.path.abspath(__file__))
	return os.path.join(script_dir, "qa", "block_map.json")


def main(argv: List[str]) -> int:
	parser = argparse.ArgumentParser(description="Find entries in block_map.json by class name combination.")
	parser.add_argument("classes", nargs="+", help="Class names to search (space- or comma-separated). Example: ax-columns fullsize width-2-columns")
	parser.add_argument("--map-file", dest="map_file", default=default_map_path(), help="Path to block_map.json (defaults to qa/block_map.json next to this script)")
	parser.add_argument("-k", "--top-k", dest="top_k", type=int, default=5, help="Number of close matches to return if no exact match (default: 5)")
	parser.add_argument("--output-json", dest="output_json", action="store_true", help="Output result as JSON")
	args = parser.parse_args(argv)

	query_classes = normalize_classes(args.classes)
	if not query_classes:
		print("Error: No class names provided after normalization.", file=sys.stderr)
		return 2

	map_path = args.map_file
	if not os.path.isfile(map_path):
		print(f"Error: map file not found: {map_path}", file=sys.stderr)
		return 2

	try:
		block_map = load_block_map(map_path)
	except Exception as e:
		print(f"Error: failed to load map file: {e}", file=sys.stderr)
		return 2

	entry_id, entry = find_exact_match(query_classes, block_map)
	if entry_id:
		if args.output_json:
			print(json.dumps({
				"exact_match": {
					"id": entry_id,
					"class_names": entry.get("class_names", []),
					"urls": entry.get("urls", []),
				}
			}, ensure_ascii=False, indent=2))
		else:
			print("Exact match found:\n")
			print(f"id: {entry_id}")
			print(f"class_names: {entry.get('class_names', [])}")
			print(f"urls ({len(entry.get('urls', []))}):")
			for u in entry.get("urls", []):
				print(f"  - {u}")
		return 0

	matches = rank_close_matches(query_classes, block_map, top_k=args.top_k)
	if args.output_json:
		print(json.dumps({
			"exact_match": None,
			"matches": [
				{"id": mid, "score": round(score, 4), "class_names": mentry.get("class_names", []), "urls": mentry.get("urls", [])}
				for (mid, score, mentry) in matches
			]
		}, ensure_ascii=False, indent=2))
	else:
		print("No exact match found. Top candidates:\n")
		for rank, (mid, score, mentry) in enumerate(matches, start=1):
			print(f"{rank}. id: {mid}")
			print(f"   score: {score:.4f}")
			print(f"   class_names: {mentry.get('class_names', [])}")
			urls = mentry.get("urls", [])
			preview = urls[:3]
			print(f"   urls: {len(urls)} total")
			for u in preview:
				print(f"     - {u}")
			if len(urls) > len(preview):
				print("     - ...")

	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))

