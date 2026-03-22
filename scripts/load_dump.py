"""Bulk-load a MusicBrainz JSON dump into GCS and BigQuery.

Downloads a single entity dump (tar.xz) from the MusicBrainz
mirror, extracts the JSONL content, chunks it into ~100 MB files,
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
import uuid
from datetime import datetime, timezone

import orjson
import requests
from google.cloud import storage, bigquery

DUMP_BASE_URL = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps"

ENTITY = os.environ["ENTITY"]
GCS_LANDING_BUCKET = os.environ.get("GCS_LANDING_BUCKET", "is-rock-alive-landing")
BQ_RAW_DATASET = os.environ.get("BQ_RAW_DATASET", "raw")
BQ_PROJECT = os.environ.get("BQ_PROJECT")

DOWNLOAD_BUFFER = 8 * 1024 * 1024  # 8 MB download buffer.
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE_MB", 100)) * 1024 * 1024  # ~100 MB blob size.
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


def check_blobs_exist(dump_date: str) -> bool:
    """Check whether blobs already exist for this entity and date.

    Uses ``max_results=1`` so the lookup short-circuits after the
    first match.

    Args:
        dump_date: Dump date string used in the blob prefix.

    Returns:
        True if at least one blob exists at the prefix.
    """
    blob_prefix = f"mb-dump/{ENTITY}/{dump_date}"
    blobs = storage.Client().list_blobs(
        GCS_LANDING_BUCKET,
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


def create_json_line(
    line: str,
    load_time: str,
    batch_id: str,
    chunk_num: int,
    dump_date: str,
) -> str:
    """Wrap a raw JSONL line with audit metadata columns.

    Parses the original JSON string, nests it under ``json_data``,
    and adds audit columns (source file, source system, batch ID,
    and landing timestamp).

    Args:
        line: A single raw JSONL line from the dump.
        load_time: ISO 8601 UTC timestamp for the load run.
        batch_id: UUID identifying this load run.
        chunk_num: Current chunk number (used in source file path).
        dump_date: Dump date string used in the source file path.

    Returns:
        A JSON string with the wrapped structure ready for upload.
    """
    parsed_dict = orjson.loads(line)
    source_file = f"mb-dump/{ENTITY}/{dump_date}/{ENTITY}_{chunk_num:03d}.jsonl"

    json_line = orjson.dumps({
        "json_data": parsed_dict,
        "_source_file": source_file,
        "_source_system": "MusicBrainz JSON Dump",
        "_batch_id": batch_id,
        "_landing_loaded_at": load_time,
    }).decode()

    return json_line


def upload_chunk(
    chunk: list[str],
    bucket: storage.Bucket,
    chunk_num: int,
    dump_date: str,
) -> None:
    """Upload a single JSONL chunk to GCS.

    Joins the buffered lines into a single newline-delimited string
    and uploads it as a blob under the dump date prefix.

    Args:
        chunk: List of decoded JSONL lines to upload.
        bucket: GCS bucket to upload into.
        chunk_num: Zero-based sequence number for the chunk file.
        dump_date: Dump date string used in the blob path.
    """
    blob_name = f"mb-dump/{ENTITY}/{dump_date}/{ENTITY}_{chunk_num:03d}.jsonl"
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
    member, buffers them into CHUNK_SIZE-byte batches, and uploads
    each batch to GCS.  Logs a warning and returns 0 if the expected
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

    load_time = datetime.now(timezone.utc).isoformat()
    batch_id = str(uuid.uuid4())

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
                json_line = create_json_line(line, load_time, batch_id, chunk_num, dump_date)
                chunk.append(json_line)
                chunk_bytes += len(json_line)

                if chunk_bytes >= CHUNK_SIZE:
                    upload_chunk(chunk, bucket, chunk_num, dump_date)
                    total_lines += len(chunk)
                    chunk_num += 1
                    chunk_bytes = 0
                    chunk = []

    if not found:
        logger.warning("Member 'mbdump/%s' not found in %s", ENTITY, dump_path)
        return 0

    if chunk:
        upload_chunk(chunk, bucket, chunk_num, dump_date)
        total_lines += len(chunk)

    logger.info(
        "Uploaded %s lines in %d chunk(s)",
        f"{total_lines:,}",
        chunk_num + (1 if chunk else 0),
    )

    return total_lines


def get_table_id() -> str:
    """Build a fully-qualified BigQuery table ID for the current entity.

    Converts entity names with hyphens to underscores
    (e.g. ``release-group`` -> ``release_group``), since BigQuery
    table names cannot contain hyphens.

    Returns:
        A fully-qualified table ID in the form
        ``project.dataset.table`` or ``dataset.table``.
    """
    table_name = ENTITY.replace("-", "_")
    if BQ_PROJECT:
        return f"{BQ_PROJECT}.{BQ_RAW_DATASET}.{table_name}_raw"
    return f"{BQ_RAW_DATASET}.{table_name}_raw"


def load_to_bigquery(dump_date: str, rows_uploaded: int | None = None) -> None:
    """Load JSONL chunks from GCS into a BigQuery raw table.

    Uses a wildcard URI to load all chunks for the entity in a single
    job.  When ``rows_uploaded`` is provided, compares the BigQuery row
    count against it and logs a warning on mismatch.

    Args:
        dump_date: Dump date string used in the GCS path.
        rows_uploaded: Expected number of rows (from extract_and_upload).
            When None, row count validation is skipped.
    """
    client = bigquery.Client(BQ_PROJECT)

    source_uri = (
        f"gs://{GCS_LANDING_BUCKET}/mb-dump/{ENTITY}/{dump_date}/*.jsonl"
    )
    table_id = get_table_id()

    logger.info("Loading %s -> %s", source_uri, table_id)

    table_schema = [
        bigquery.SchemaField(name="json_data", field_type="JSON", mode="REQUIRED"),
        bigquery.SchemaField(name="_source_file", field_type="STRING", mode="REQUIRED"),
        bigquery.SchemaField(name="_source_system", field_type="STRING", mode="REQUIRED"),
        bigquery.SchemaField(name="_batch_id", field_type="STRING", mode="REQUIRED"),
        bigquery.SchemaField(name="_landing_loaded_at", field_type="TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField(name="_raw_loaded_at", field_type="TIMESTAMP", mode="NULLABLE")
    ]

    job_config = bigquery.LoadJobConfig(
        schema=table_schema,
        source_format="NEWLINE_DELIMITED_JSON",
        write_disposition="WRITE_TRUNCATE",
        clustering_fields=["_source_system", "_raw_loaded_at"],
    )

    load_job = client.load_table_from_uri(source_uri, table_id, job_config=job_config)
    load_job.result()

    logger.info("Setting _raw_loaded_at on %s", table_id)
    update_query = (
        f"UPDATE `{table_id}` "
        "SET _raw_loaded_at = CURRENT_TIMESTAMP() "
        "WHERE _raw_loaded_at IS NULL"
    )
    client.query(update_query).result()

    table = client.get_table(table_id)

    if rows_uploaded is not None:
        logger.info(
            "Loaded %s rows into %s (expected %s)",
            f"{table.num_rows:,}",
            table_id,
            f"{rows_uploaded:,}",
        )
        if table.num_rows != rows_uploaded:
            logger.warning(
                "Row count mismatch: BigQuery has %s rows, but %s lines were uploaded",
                f"{table.num_rows:,}",
                f"{rows_uploaded:,}",
            )
    else:
        logger.info("Loaded %s rows into %s", f"{table.num_rows:,}", table_id)


def main() -> None:
    """Orchestrate the full dump-load pipeline for one entity.

    Flow: fetch latest dump date → download and upload to GCS
    (skipped if blobs already exist) → load into BigQuery.

    The GCS upload is skipped when blobs already exist for the
    entity and dump date.  The BigQuery load always runs, making
    it safe to rerun after a failed BQ load without re-downloading.

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

    t0 = time.monotonic()
    logger.info("=== bulk_load: entity=%s ===", ENTITY)

    dump_date = get_latest_dump_date()
    dump_url = f"{DUMP_BASE_URL}/{dump_date}/{ENTITY}.tar.xz"

    rows_uploaded = None

    if check_blobs_exist(dump_date):
        logger.info(
            "GCS blobs already exist at gs://%s/mb-dump/%s/%s/, skipping upload",
            GCS_LANDING_BUCKET, ENTITY, dump_date,
        )
    else:
        dump_path = download_dump(dump_url)

        try:
            rows_uploaded = extract_and_upload(dump_path, dump_date)
        finally:
            os.unlink(dump_path)
            logger.info("Cleaned up temp file %s", dump_path)

    load_to_bigquery(dump_date, rows_uploaded)

    elapsed = time.monotonic() - t0
    logger.info("=== Done in %.0fs ===", elapsed)


if __name__ == "__main__":
    main()
