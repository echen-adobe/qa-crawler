# Repository Guidelines

## Project Structure & Module Organization
Core package code lives in `src/qa_crawler`, with CLI shims in `cli/`, search and sync routines, and shared config helpers. The asynchronous Playwright crawler, loggers, and sitemap utilities stay in `backend/`; treat that directory as operational tooling that feeds the packaged commands. Helper automation scripts reside in `scripts/`, automated checks in `tests/`, and generated artifacts (block maps, screenshots, diffs) under `output/` for manual review only.

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate`: spin up a Python 3.10 virtualenv.
- `pip install -r requirements.txt && pip install -e .`: install crawler dependencies and the package in editable mode.
- `playwright install`: download browser drivers required by `backend/crawl.py`.
- `python -m qa_crawler.cli.search "hero centered" --path backend/qa/block_map.json`: exercise the packaged search CLI.
- `pytest`: run the full suite; narrow scope with `pytest tests/test_sync_block_map.py -k missing` when iterating.
- `python scripts/sync_block_map.py --bucket <bucket>`: sync the block map from GCS, defaulting to `QA_CRAWLER_GCS_BUCKET` if exported.

## Coding Style & Naming Conventions
Stick to PEP 8 with four-space indentation and `snake_case` for functions, variables, and filenames. Keep CLI modules as thin facades that call the underlying package functions, and prefer explicit imports. Extend existing type hints when touching public functions, and mirror the descriptive class names already used in `backend/loggers/` for any new logger or reporter.

## Testing Guidelines
Pytest powers the suite (`tests/test_*.py`). Mirror production fixtures inside `tests/url_parsing/` or neighbouring directories and load them via `Path(__file__).parent`. Favour fast unit coverage by feeding small block-map excerpts or mocked HTTP responses; reserve real Playwright sessions for manual verification and document them in the PR description.

## Commit & Pull Request Guidelines
Commits use short, imperative subjects (`shifted cli structure`, `added tests`) with optional explanatory bodies when behaviour changes. Bundle related updates together and note any migrations or new datasets in the commit body. Pull requests should link the motivating issue, summarise impact, list manual verification (CLI runs, Playwright smoke checks), and attach sample output whenever block-map formats change.

## Environment & Configuration Tips
Load `.env` early—`backend/crawl.py` calls `load_dotenv()`—to provide credentials, sitemap hosts, and Playwright settings. Override the default block map (`backend/qa/block_map.json`) per run with `--path` or environment variables, and keep bulky artifacts in `output/` while ensuring they stay out of commits. Production crawls run on EC2 via cron; after each run push the refreshed block map to `s3://express-block-maps/block_map.json` with `scripts/sync_block_map_s3.py`, and fall back to `scripts/download_from_s3.py` when that bucket is the source of truth.
