#!/usr/bin/env python3
"""Download the latest block map from S3 and archive the previous copy."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import BotoCoreError, ClientError


DEFAULT_S3_URL = "https://express-block-maps.s3.us-east-2.amazonaws.com/block_map.json"


def parse_s3_url(url: str) -> Tuple[str, str]:
    """Return (bucket, key) from an S3-style HTTPS or s3:// URL."""

    parsed = urlparse(url)
    if parsed.scheme == "s3":
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"Invalid S3 URL: {url}")
        return bucket, key

    if parsed.scheme in {"http", "https"} and ".s3" in parsed.netloc:
        host_parts = parsed.netloc.split(".s3", 1)
        bucket = host_parts[0]
        key = parsed.path.lstrip("/")
        if not bucket or not key:
            raise ValueError(f"Invalid S3 URL: {url}")
        return bucket, key

    raise ValueError(f"Unsupported S3 URL format: {url}")


def archive_existing_block_map(block_map_path: Path, archive_dir: Path) -> Path | None:
    """Move the current block map into the archive directory, returning new location."""

    if not block_map_path.exists():
        return None

    archive_dir.mkdir(parents=True, exist_ok=True)
    base_name = block_map_path.name
    timestamp = dt.datetime.now().strftime("%H%M%S")
    archive_path = archive_dir / base_name

    if archive_path.exists():
        # Avoid overwriting an existing archive from the same day
        archive_path = archive_dir / f"{block_map_path.stem}_{timestamp}{block_map_path.suffix}"

    shutil.move(str(block_map_path), archive_path)
    return archive_path


def download_block_map(bucket: str, key: str, destination: Path) -> None:
    """Download an S3 object and write it to destination, validating JSON."""

    client = boto3.client("s3")
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        client.download_file(bucket, key, str(tmp_path))
    except (BotoCoreError, ClientError) as exc:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download s3://{bucket}/{key}: {exc}") from exc

    try:
        data = json.loads(tmp_path.read_text(encoding="utf-8"))
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise ValueError(f"Downloaded file is not valid JSON: {exc}") from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync data/qa/block_map.json from S3")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (auto-detected)",
    )
    parser.add_argument(
        "--s3-url",
        default=DEFAULT_S3_URL,
        help="HTTPS or s3:// URL to the block_map.json object",
    )
    parser.add_argument(
        "--archive-date",
        default=dt.date.today().isoformat(),
        help="Archive folder name under past_block_maps (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--destination",
        default=str(Path("data") / "qa" / "block_map.json"),
        help="Path (relative to repo root) to overwrite with the downloaded block map",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    destination = (repo_root / args.destination).resolve()
    archive_dir = repo_root / "past_block_maps" / args.archive_date

    try:
        bucket, key = parse_s3_url(args.s3_url)
    except ValueError as exc:
        parser.error(str(exc))

    archived_path = archive_existing_block_map(destination, archive_dir)
    if archived_path:
        print(f"Archived previous block map to {archived_path}")

    try:
        download_block_map(bucket, key, destination)
    except Exception as exc:
        # Restore the archived file if download fails
        if archived_path and not destination.exists():
            shutil.move(str(archived_path), destination)
            print("Download failed; restored previous block map.")
        print(exc)
        return 1

    print(f"Downloaded s3://{bucket}/{key} to {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
