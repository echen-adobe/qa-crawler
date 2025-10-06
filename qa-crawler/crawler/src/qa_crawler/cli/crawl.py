from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None or __package__ == "":  # pragma: no cover - script execution fallback
    repo_src = Path(__file__).resolve().parents[2]
    if str(repo_src) not in sys.path:
        sys.path.insert(0, str(repo_src))

from qa_crawler.crawl import main as crawl_main


def main() -> int:
    return crawl_main()
