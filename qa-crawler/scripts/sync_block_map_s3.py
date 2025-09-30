#!/usr/bin/env python3
"""Sync the local block map with S3 (upload by default, download on demand)."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from download_from_s3 import (
    DEFAULT_S3_URL,
    archive_existing_block_map,
    download_block_map,
    parse_s3_url,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Upload or download block_map.json with S3")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root (auto-detected)",
    )
    parser.add_argument(
        "--s3-url",
        default=DEFAULT_S3_URL,
        help="Target S3 object URL (HTTPS or s3://)",
    )
    parser.add_argument(
        "--source",
        default=str(Path("backend") / "qa" / "block_map.json"),
        help="Local block map to upload (relative to repo root)",
    )
    parser.add_argument(
        "--destination",
        default=str(Path("backend") / "qa" / "block_map.json"),
        help="Download destination (relative to repo root)",
    )
    parser.add_argument(
        "--archive-date",
        default=dt.date.today().isoformat(),
        help="Archive folder name under past_block_maps (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--direction",
        choices=("upload", "download"),
        default="upload",
        help="Sync direction: upload pushes local changes to S3; download pulls from S3",
    )
    return parser


def validate_json_file(path: Path) -> None:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive logging
        raise ValueError(f"{path} does not contain valid JSON: {exc}") from exc


def archive_remote_block_map(
    client,
    bucket: str,
    key: str,
    archive_dir: Path,
    archive_date: str,
) -> tuple[Path | None, str | None]:
    """Archive the current S3 object locally and in S3."""

    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey"}:
            return None, None
        raise

    archive_dir.mkdir(parents=True, exist_ok=True)
    obj_name = Path(key).name or "block_map.json"
    archive_path = archive_dir / obj_name
    if archive_path.exists():
        timestamp = dt.datetime.now().strftime("%H%M%S")
        archive_path = archive_dir / f"{Path(obj_name).stem}_{timestamp}{Path(obj_name).suffix}"

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        client.download_file(bucket, key, str(tmp_path))
        shutil.move(str(tmp_path), archive_path)
    except (BotoCoreError, ClientError) as exc:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to archive s3://{bucket}/{key} locally: {exc}") from exc

    archive_key = f"past_block_maps/{archive_date}/{obj_name}"
    copy_source = {"Bucket": bucket, "Key": key}
    try:
        client.copy(copy_source, bucket, archive_key)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(
            f"Failed to copy s3://{bucket}/{key} to s3://{bucket}/{archive_key}: {exc}"
        ) from exc

    return archive_path, archive_key


def upload_block_map(
    client,
    bucket: str,
    key: str,
    source_path: Path,
) -> None:
    extra_args = {"ContentType": "application/json"}
    try:
        client.upload_file(str(source_path), bucket, key, ExtraArgs=extra_args)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"Failed to upload {source_path} to s3://{bucket}/{key}: {exc}") from exc


def sync_upload(
    client,
    bucket: str,
    key: str,
    source_path: Path,
    archive_dir: Path,
    archive_date: str,
) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived_local, archived_remote = archive_remote_block_map(
        client,
        bucket,
        key,
        archive_dir,
        archive_date=archive_date,
    )
    if archived_local:
        print(f"Archived previous S3 block map locally to {archived_local}")
    if archived_remote:
        print(f"Copied previous S3 block map to s3://{bucket}/{archived_remote}")

    validate_json_file(source_path)
    upload_block_map(client, bucket, key, source_path)
    print(f"Uploaded {source_path} to s3://{bucket}/{key}")


def sync_download(
    bucket: str,
    key: str,
    destination: Path,
    archive_dir: Path,
) -> None:
    archived_local = archive_existing_block_map(destination, archive_dir)
    if archived_local:
        print(f"Archived previous local block map to {archived_local}")

    download_block_map(bucket, key, destination)
    print(f"Downloaded s3://{bucket}/{key} to {destination}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    archive_dir = repo_root / "past_block_maps" / args.archive_date

    try:
        bucket, key = parse_s3_url(args.s3_url)
    except ValueError as exc:
        parser.error(str(exc))

    if args.direction == "upload":
        source_path = (repo_root / args.source).resolve()
        if not source_path.exists():
            parser.error(f"Source not found: {source_path}")

        client = boto3.client("s3")
        try:
            sync_upload(client, bucket, key, source_path, archive_dir, args.archive_date)
        except Exception as exc:
            print(exc)
            return 1

        return 0

    destination = (repo_root / args.destination).resolve()
    try:
        sync_download(bucket, key, destination, archive_dir)
    except Exception as exc:
        print(exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
