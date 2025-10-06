#!/usr/bin/env python3
import argparse
import os
from pathlib import Path


def _download_gcs_prefix(bucket_name: str, prefix: str, dest_dir: Path) -> int:
    try:
        from google.cloud import storage  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "google-cloud-storage is required. Please install dependencies and retry."
        ) from e

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    dest_dir.mkdir(parents=True, exist_ok=True)

    blobs_iter = client.list_blobs(bucket_or_name=bucket, prefix=prefix)
    count = 0
    for blob in blobs_iter:
        if blob.name.endswith("/"):
            continue
        relative = blob.name[len(prefix) :] if blob.name.startswith(prefix) else blob.name
        local_path = dest_dir / relative
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))
        count += 1
        print(f"Downloaded gs://{bucket_name}/{blob.name} -> {local_path}")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync from GCS bucket into local output directory")
    parser.add_argument("--bucket", default=os.environ.get("QA_CRAWLER_GCS_BUCKET"), help="GCS bucket name or set QA_CRAWLER_GCS_BUCKET")
    parser.add_argument("--gcs-prefix", default="", help="Optional GCS prefix to pull (e.g. 'output/')")
    parser.add_argument("--dest", default=str(Path(__file__).resolve().parents[1] / "output"), help="Local destination directory (defaults to repo output/)")
    args = parser.parse_args()

    if not args.bucket:
        print("--bucket is required (or set QA_CRAWLER_GCS_BUCKET)")
        return 1

    dest_dir = Path(args.dest)
    try:
        count = _download_gcs_prefix(args.bucket, args.gcs_prefix, dest_dir)
    except Exception as e:
        print(f"Download failed: {e}")
        return 2

    if count == 0:
        print("No objects found to download.")
    else:
        print(f"Downloaded {count} objects to {dest_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

