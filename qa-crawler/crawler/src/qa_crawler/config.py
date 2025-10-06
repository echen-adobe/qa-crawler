import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "output"
DATA_DIR = REPO_ROOT / "data"
QA_DATA_DIR = DATA_DIR / "qa"
SITEMAPS_DIR = DATA_DIR / "sitemaps"
DOM_SNAPSHOT_DIR = QA_DATA_DIR / "dom_snapshots"
BLOCK_MAP_OUTPUT_DIR = OUTPUT_DIR / "block_maps"
CONTROL_SCREENSHOT_DIR = QA_DATA_DIR / "control"
EXPERIMENTAL_SCREENSHOT_DIR = QA_DATA_DIR / "experimental"
DIFF_SCREENSHOT_DIR = QA_DATA_DIR / "diff"
DEFAULT_BLOCK_MAP = QA_DATA_DIR / "block_map.json"
FAILED_URLS_PATH = QA_DATA_DIR / "failed_urls.json"
SOURCE_FILES_PATH = QA_DATA_DIR / "source_files.json"


def resolve_block_map_path(explicit_path: str | None = None) -> str:
    if explicit_path:
        return explicit_path
    return str(DEFAULT_BLOCK_MAP)


def ensure_data_directories() -> None:
    """Ensure on-disk directories required by loggers exist."""

    for path in (
        DATA_DIR,
        QA_DATA_DIR,
        DOM_SNAPSHOT_DIR,
        CONTROL_SCREENSHOT_DIR,
        EXPERIMENTAL_SCREENSHOT_DIR,
        DIFF_SCREENSHOT_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
