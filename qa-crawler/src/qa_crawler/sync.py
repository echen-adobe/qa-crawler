#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
from pathlib import Path

from .config import REPO_ROOT


def _upload_directory_to_gcs(local_dir: Path, bucket_name: str, prefix: str = "") -> None:
    """Upload all files under local_dir to a GCS bucket, preserving structure.

    Objects are written as "<prefix>/<relative_path>" (prefix omitted if empty).
    Requires Application Default Credentials (e.g. `gcloud auth application-default login`).
    """
    try:
        from google.cloud import storage  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "google-cloud-storage is required. Please install dependencies and retry."
        ) from e

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    root = Path(local_dir).resolve()
    if not root.exists():
        print(f"Local directory not found: {root}")
        return

    uploaded = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root)
        blob_name_path = Path(prefix) / rel_path if prefix else rel_path
        blob_name = str(blob_name_path).replace("\\", "/")
        blob = bucket.blob(blob_name)
        blob.upload_from_filename(str(path))
        uploaded += 1
        print(f"Uploaded {path} -> gs://{bucket_name}/{blob_name}")

    if uploaded == 0:
        print(f"No files found to upload in {root}")
    else:
        print(f"Uploaded {uploaded} files to gs://{bucket_name}/{prefix}".rstrip("/"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync qa/block_map.json into output/<YYYY-MM-DD>/block_map.json and optionally upload output/ to GCS."
    )
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Date folder name (YYYY-MM-DD), defaults to today",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("QA_CRAWLER_GCS_BUCKET"),
        help="GCS bucket name to upload to (or set QA_CRAWLER_GCS_BUCKET)",
    )
    parser.add_argument(
        "--gcs-prefix",
        default="",
        help="Optional GCS object prefix when uploading (e.g. 'output/')",
    )
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Do not upload to GCS even if --bucket is provided",
    )
    args = parser.parse_args()

    qa_block_map = REPO_ROOT / "backend" / "qa" / "block_map.json"
    out_dir = REPO_ROOT / "output" / args.date
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "block_map.json"

    if not qa_block_map.exists():
        print(f"Source not found: {qa_block_map}")
        return 1

    try:
        with qa_block_map.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Invalid JSON in {qa_block_map}: {e}")
        return 2

    with out_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Wrote {out_file}")

    # Optionally upload the entire output/ directory to GCS
    if args.bucket and not args.no_upload:
        output_root = REPO_ROOT / "output"
        try:
            _upload_directory_to_gcs(output_root, args.bucket, args.gcs_prefix)
        except Exception as e:
            print(f"Upload to GCS failed: {e}")
            return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

