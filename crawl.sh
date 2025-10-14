#!/usr/bin/env bash
set -euo pipefail
cd qa-crawler
source venv/bin/activate
PYTHONPATH=src python3 -m qa_crawler.crawl