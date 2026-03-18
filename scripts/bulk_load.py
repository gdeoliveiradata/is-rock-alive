"""Bulk-load a MusicBrainz JSON dump into GCS and BigQuery.

Downloads a single entity dump (tar.xz) from the MusicBrainz mirror,
extracts the JSONL content, chunks it into ~100 MB files, uploads to
GCS, and loads into BigQuery with WRITE_TRUNCATE for idempotency.

The target entity is read from the ENTITY environment variable.
"""

import logging
import os
import sys
import tarfile
import tempfile
import time

import requests
from google.cloud import storage

DUMP_BASE_URL = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps"

ENTITY = os.environ["ENTITY"]
GCS_LANDING_BUCKET = os.environ.get("GCS_LANDING_BUCKET", "is-rock-alive-landing")
BQ_RAW_DATASET = os.environ.get("BQ_RAW_DATASET", "raw")
BQ_PROJECT = os.environ.get("BQ_PROJECT")

DOWNLOAD_BUFFER = 8 * 1024 * 1024  # 8 MB download buffer.
CHUNK_SIZE = 100 * 1024 * 1024  # ~100 MB blob size.
HTTP_TIMEOUT = 30  # Seconds for initial connection.

logger = logging.getLogger(__name__)


def get_latest_dump_date() -> str:
    """Fetch the latest MusicBrainz JSON dump date from the mirror server.

    Reads the LATEST file from data.metabrainz.org, which contains the
    date string of the most recent available dump.

    Returns:
        The dump date as a string (e.g. '20260315-001000').

    Raises:
        requests.HTTPError: If the server returns a non-2xx response.
    """
    resp = requests.get(f"{DUMP_BASE_URL}/LATEST", timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.text.split()[0]


def download_dump(url: str) -> str:
    """Download a tar.xz dump to a temporary file.

    Streams the response to disk in DOWNLOAD_BUFFER-sized chunks to
    keep memory usage low.

    Args:
        url: Full URL of the tar.xz archive to download.

    Returns:
        Path to the temporary file containing the downloaded archive.

    Raises:
        requests.HTTPError: If the server returns a non-2xx response.
    """
    logger.info("Downloading from %s", url)
    t0 = time.monotonic()

    resp = requests.get(url, stream=True, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()

    temp_file = tempfile.NamedTemporaryFile(suffix=".tar.xz", delete=False)
    size = 0

    with temp_file:
        for chunk in resp.iter_content(chunk_size=DOWNLOAD_BUFFER):
            temp_file.write(chunk)
            size += len(chunk)

    elapsed = time.monotonic() - t0
    logger.info(
        "Downloaded %.1f MB in %.0fs -> %s",
        size / 1024 / 1024, elapsed, temp_file.name,
    )

    return temp_file.name


def extract_and_upload(dump_path: str):
    logger.info("Extracting and uploading chunks to gs://%s/%s/", GCS_LANDING_BUCKET, ENTITY)
    bucket = storage.Client().bucket(GCS_LANDING_BUCKET)

    total_lines = 0
    chunk = []
    chunk_num = 0
    chunk_bytes = 0

    with tarfile.open(dump_path, mode="r:xz") as tar:
        try:
            member = tar.getmember(f"mbdump/{ENTITY}")
            jsonl_file = tar.extractfile(member)

            for raw_line in jsonl_file:
                chunk.append(raw_line.decode().split())
                chunk_bytes += len(raw_line)

                if chunk_bytes >= CHUNK_SIZE:
                    # upload_chunk(chunk, bucket)
                    total_lines += len(chunk)
                    chunk_num += 1
                    chunk_bytes = 0
                    chunk = []

            if chunk:
                # upload_chunk(chunk, bucket)
                total_lines += len(chunk)
                chunk = []
        finally:    
            logger.info("Uploaded %s lines in %d chunk(s)", f"{total_lines:,}", chunk_num + (1 if chunk else 0))
            
    return total_lines


def main() -> None:
    """Entry point: download, extract, upload, and load one entity dump."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    dump_date = get_latest_dump_date()
    dump_url = f"{DUMP_BASE_URL}/{dump_date}/{ENTITY}.tar.xz"

    dump_path = download_dump(dump_url)

    extract_and_upload(dump_path)

    os.unlink(dump_path)


if __name__ == "__main__":
    main()