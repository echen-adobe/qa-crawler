import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_BLOCK_MAP = BACKEND_DIR / "qa" / "block_map.json"


def resolve_block_map_path(explicit_path: str | None = None) -> str:
    if explicit_path:
        return explicit_path
    return str(DEFAULT_BLOCK_MAP)

