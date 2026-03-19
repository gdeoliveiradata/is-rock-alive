"""Bulk-load a MusicBrainz JSON dump into GCS and BigQuery.

Downloads a single entity dump (tar.xz) from the MusicBrainz
mirror, extracts the JSONL content, chunks it into ~250 MB files,
uploads to GCS, and loads into BigQuery with WRITE_TRUNCATE for
idempotency.

The target entity is read from the ENTITY environment variable.
"""

import logging
import os
import sys
import tarfile
import tempfile
import time

import requests
from google.cloud import storage, bigquery

DUMP_BASE_URL = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps"

ENTITY = os.environ["ENTITY"]
GCS_LANDING_BUCKET = os.environ.get("GCS_LANDING_BUCKET", "is-rock-alive-landing")
BQ_RAW_DATASET = os.environ.get("BQ_RAW_DATASET", "raw")
BQ_PROJECT = os.environ.get("BQ_PROJECT")

DOWNLOAD_BUFFER = 8 * 1024 * 1024  # 8 MB download buffer.
CHUNK_SIZE = 250 * 1024 * 1024  # ~250 MB blob size.
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


def check_blobs_exist(
    bucket: str,
    entity: str,
    dump_date: str,
) -> bool:
    """Check whether blobs already exist for this entity and date.

    Uses ``max_results=1`` so the lookup short-circuits after the
    first match.

    Args:
        bucket: GCS bucket name to check.
        entity: MusicBrainz entity name (e.g. 'event').
        dump_date: Dump date string used in the blob prefix.

    Returns:
        True if at least one blob exists at the prefix.
    """
    blob_prefix = f"mb-dump/{entity}/{dump_date}"
    blobs = storage.Client().list_blobs(
        bucket,
        prefix=blob_prefix,
        max_results=1,
    )
    return any(blobs)


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
        size / 1024 / 1024,
        elapsed,
        temp_file.name,
    )

    return temp_file.name


def upload_chunk(
    chunk: list[str],
    bucket: storage.Bucket,
    chunk_num: int,
    entity: str,
    dump_date: str,
) -> None:
    """Upload a single JSONL chunk to GCS.

    Joins the buffered lines into a single newline-delimited string
    and uploads it as a blob under the dump date prefix.

    Args:
        chunk: List of decoded JSONL lines to upload.
        bucket: GCS bucket to upload into.
        chunk_num: Zero-based sequence number for the chunk file.
        entity: MusicBrainz entity name (e.g. 'event').
        dump_date: Dump date string used in the blob path.
    """
    blob_name = f"mb-dump/{entity}/{dump_date}/{entity}_{chunk_num:03d}.jsonl"
    blob = bucket.blob(blob_name)

    data = "\n".join(chunk) + "\n"
    logger.info(
        "  %s: %s lines, %.1f MB",
        blob_name,
        f"{len(chunk):,}",
        len(data) / 1024 / 1024,
    )
    blob.upload_from_string(data, content_type="application/jsonl")


def extract_and_upload(dump_path: str, dump_date: str) -> int:
    """Extract JSONL from a tar.xz archive and upload to GCS.

    Opens the dump archive, reads lines from the matching entity
    member, buffers them into CHUNK_SIZE batches, and uploads each
    batch to GCS.  Logs a warning and returns 0 if the expected
    member is not found.

    Args:
        dump_path: Local path to the downloaded tar.xz archive.
        dump_date: Dump date string used in the GCS blob path.

    Returns:
        Total number of JSONL lines uploaded.
    """
    logger.info(
        "Extracting and uploading chunks to gs://%s/%s/",
        GCS_LANDING_BUCKET,
        ENTITY,
    )
    bucket = storage.Client().bucket(GCS_LANDING_BUCKET)

    total_lines = 0
    chunk = []
    chunk_num = 0
    chunk_bytes = 0

    found = False

    with tarfile.open(dump_path, mode="r:xz") as tar:
        for member in tar:
            if member.name != f"mbdump/{ENTITY}":
                continue

            found = True
            jsonl_file = tar.extractfile(member)
            if jsonl_file is None:
                continue

            for raw_line in jsonl_file:
                line = raw_line.decode().strip()
                chunk.append(line)
                chunk_bytes += len(line)

                if chunk_bytes >= CHUNK_SIZE:
                    upload_chunk(chunk, bucket, chunk_num, ENTITY, dump_date)
                    total_lines += len(chunk)
                    chunk_num += 1
                    chunk_bytes = 0
                    chunk = []

    if not found:
        logger.warning("Member 'mbdump/%s' not found in %s", ENTITY, dump_path)
        return 0

    if chunk:
        upload_chunk(chunk, bucket, chunk_num, ENTITY, dump_date)
        total_lines += len(chunk)

    logger.info(
        "Uploaded %s lines in %d chunk(s)",
        f"{total_lines:,}",
        chunk_num + (1 if chunk else 0),
    )

    return total_lines


def load_to_bigquery():
    


def main() -> None:
    """Orchestrate the full dump-load pipeline for one entity.

    Flow: fetch latest dump date → skip check → download → extract
    and upload to GCS → clean up temp file.

    Exits cleanly (no error) if blobs already exist for the entity
    and dump date — to rerun, delete the GCS files first.

    The temp file is always removed, even if extraction fails.

    Configuration is read from environment variables at module level:
    ``ENTITY`` (required), ``GCS_LANDING_BUCKET``, ``BQ_RAW_DATASET``,
    and ``BQ_PROJECT`` (optional, with defaults).
    """
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    dump_date = get_latest_dump_date()
    dump_url = f"{DUMP_BASE_URL}/{dump_date}/{ENTITY}.tar.xz"

    blob_exists = check_blobs_exist(GCS_LANDING_BUCKET, ENTITY, dump_date)

    if blob_exists:
        logger.info("Dump already available at %s", GCS_LANDING_BUCKET)
    else:
        dump_path = download_dump(dump_url)

        try:
            extract_and_upload(dump_path, dump_date)
        finally:
            os.unlink(dump_path)
            logger.info("Cleaned up temp file %s", dump_path)


if __name__ == "__main__":
    main()
