#!/usr/bin/env bash
set -euo pipefail

# Ensure the script runs from the repository root.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

TARGET_DIRS=(
  "qa-crawler/data/qa/control"
  "qa-crawler/data/qa/diff"
  "qa-crawler/data/qa/dom_snapshots"
  "qa-crawler/data/qa/experimental"
)

for dir in "${TARGET_DIRS[@]}"; do
  if [[ -d "$dir" ]]; then
    # Remove everything inside the directory but keep the directory itself.
    find "$dir" -mindepth 1 -delete
  else
    echo "Skipping missing directory: $dir" >&2
  fi
done
