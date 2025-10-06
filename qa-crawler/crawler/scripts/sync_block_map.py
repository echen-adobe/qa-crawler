#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync qa/block_map.json into qa-crawler/output/<YYYY-MM-DD>/block_map.json")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="Repo root (auto-detected)")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="Date folder name (YYYY-MM-DD), defaults to today")
    args = parser.parse_args()

    repo_root = Path(args.root)
    qa_block_map = repo_root / "data" / "qa" / "block_map.json"
    out_dir = repo_root / "output" / args.date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "block_map.json"

    if not qa_block_map.exists():
        print(f"Source not found: {qa_block_map}")
        return 1

    # Validate JSON to avoid copying corrupt files
    try:
        with qa_block_map.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Invalid JSON in {qa_block_map}: {e}")
        return 2

    # Write pretty JSON at destination
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
