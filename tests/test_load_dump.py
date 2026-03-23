"""Tests for scripts/load_dump.py."""

import io
import json
import lzma
import os
import tarfile
import tempfile
from unittest.mock import MagicMock, call, patch

import orjson
import pytest

# Set required env vars before importing the module (read at import time).
os.environ.setdefault("ENTITY", "event")

from scripts import load_dump


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_entity(monkeypatch):
    """Ensure every test starts with a known ENTITY value."""
    monkeypatch.setattr(load_dump, "ENTITY", "event")


@pytest.fixture()
def sample_json_lines():
    """Return a list of raw JSONL strings as they appear in a MusicBrainz dump."""
    return [
        json.dumps({"id": "aaa-111", "name": "Rock Fest"}),
        json.dumps({"id": "bbb-222", "name": "Jazz Night"}),
        json.dumps({"id": "ccc-333", "name": "Blues Hour"}),
    ]


def _make_tar_xz(entity: str, lines: list[str]) -> bytes:
    """Build an in-memory tar.xz archive containing a single JSONL member."""
    jsonl_bytes = ("\n".join(lines) + "\n").encode()

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        info = tarfile.TarInfo(name=f"mbdump/{entity}")
        info.size = len(jsonl_bytes)
        tar.addfile(info, io.BytesIO(jsonl_bytes))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# create_json_line
# ---------------------------------------------------------------------------

class TestCreateJsonLine:
    def test_wraps_original_json_under_json_data(self):
        raw = json.dumps({"id": "abc-123", "name": "Test Event"})
        result = load_dump.create_json_line(
            raw, "2026-03-18T00:00:00+00:00", "batch-1", 0, "20260318-001000"
        )
        parsed = orjson.loads(result)

        assert parsed["json_data"] == {"id": "abc-123", "name": "Test Event"}

    def test_adds_audit_columns(self):
        raw = json.dumps({"id": "abc-123"})
        result = load_dump.create_json_line(
            raw, "2026-03-18T00:00:00+00:00", "batch-1", 5, "20260318-001000"
        )
        parsed = orjson.loads(result)

        assert parsed["_source_file"] == "mb-dump/event/20260318-001000/event_005.jsonl"
        assert parsed["_source_system"] == "MusicBrainz JSON Dump"
        assert parsed["_batch_id"] == "batch-1"
        assert parsed["_landing_loaded_at"] == "2026-03-18T00:00:00+00:00"

    def test_original_json_is_preserved_untouched(self):
        original = {"id": "x", "nested": {"a": [1, 2, 3]}}
        raw = json.dumps(original)
        result = load_dump.create_json_line(raw, "t", "b", 0, "d")
        parsed = orjson.loads(result)

        assert parsed["json_data"] == original

    def test_source_file_uses_entity_and_chunk_num(self, monkeypatch):
        monkeypatch.setattr(load_dump, "ENTITY", "release-group")
        raw = json.dumps({"id": "1"})
        result = load_dump.create_json_line(raw, "t", "b", 12, "20260318-001000")
        parsed = orjson.loads(result)

        assert parsed["_source_file"] == "mb-dump/release-group/20260318-001000/release-group_012.jsonl"

    def test_returns_valid_json_string(self):
        raw = json.dumps({"id": "1"})
        result = load_dump.create_json_line(raw, "t", "b", 0, "d")

        assert isinstance(result, str)
        orjson.loads(result)  # Should not raise.


# ---------------------------------------------------------------------------
# get_table_id
# ---------------------------------------------------------------------------

class TestGetTableId:
    def test_with_project(self, monkeypatch):
        monkeypatch.setattr(load_dump, "BQ_PROJECT", "my-project")
        monkeypatch.setattr(load_dump, "BQ_RAW_DATASET", "raw")
        monkeypatch.setattr(load_dump, "ENTITY", "event")

        assert load_dump.get_table_id() == "my-project.raw.event_raw"

    def test_without_project(self, monkeypatch):
        monkeypatch.setattr(load_dump, "BQ_PROJECT", None)
        monkeypatch.setattr(load_dump, "BQ_RAW_DATASET", "raw")

        assert load_dump.get_table_id() == "raw.event_raw"

    def test_hyphen_entity_converted_to_underscore(self, monkeypatch):
        monkeypatch.setattr(load_dump, "ENTITY", "release-group")
        monkeypatch.setattr(load_dump, "BQ_PROJECT", "proj")
        monkeypatch.setattr(load_dump, "BQ_RAW_DATASET", "raw")

        assert load_dump.get_table_id() == "proj.raw.release_group_raw"


# ---------------------------------------------------------------------------
# get_latest_dump_date
# ---------------------------------------------------------------------------

class TestGetLatestDumpDate:
    @patch("scripts.load_dump.requests.get")
    def test_returns_date_string(self, mock_get):
        mock_get.return_value.text = "20260318-001000\n"
        assert load_dump.get_latest_dump_date() == "20260318-001000"

    @patch("scripts.load_dump.requests.get")
    def test_calls_raise_for_status(self, mock_get):
        load_dump.get_latest_dump_date()
        mock_get.return_value.raise_for_status.assert_called_once()

    @patch("scripts.load_dump.requests.get")
    def test_strips_trailing_whitespace(self, mock_get):
        mock_get.return_value.text = "  20260318-001000  \n"
        assert load_dump.get_latest_dump_date() == "20260318-001000"


# ---------------------------------------------------------------------------
# check_blobs_exist
# ---------------------------------------------------------------------------

class TestCheckBlobsExist:
    @patch("scripts.load_dump.storage.Client")
    def test_returns_true_when_blobs_found(self, mock_client):
        mock_client.return_value.list_blobs.return_value = iter(["blob1"])
        assert load_dump.check_blobs_exist("20260318-001000") is True

    @patch("scripts.load_dump.storage.Client")
    def test_returns_false_when_no_blobs(self, mock_client):
        mock_client.return_value.list_blobs.return_value = iter([])
        assert load_dump.check_blobs_exist("20260318-001000") is False

    @patch("scripts.load_dump.storage.Client")
    def test_uses_correct_prefix(self, mock_client):
        mock_client.return_value.list_blobs.return_value = iter([])
        load_dump.check_blobs_exist("20260318-001000")

        mock_client.return_value.list_blobs.assert_called_once_with(
            "is-rock-alive-landing",
            prefix="mb-dump/event/20260318-001000",
            max_results=1,
        )


# ---------------------------------------------------------------------------
# download_dump
# ---------------------------------------------------------------------------

class TestDownloadDump:
    @patch("scripts.load_dump.requests.get")
    def test_writes_streamed_content_to_temp_file(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_get.return_value = mock_resp

        path = load_dump.download_dump("http://example.com/dump.tar.xz")

        try:
            with open(path, "rb") as f:
                assert f.read() == b"chunk1chunk2"
        finally:
            os.unlink(path)

    @patch("scripts.load_dump.requests.get")
    def test_returns_path_ending_in_tar_xz(self, mock_get):
        mock_get.return_value.iter_content.return_value = [b"data"]

        path = load_dump.download_dump("http://example.com/dump.tar.xz")
        try:
            assert path.endswith(".tar.xz")
        finally:
            os.unlink(path)

    @patch("scripts.load_dump.requests.get")
    def test_calls_raise_for_status(self, mock_get):
        mock_get.return_value.iter_content.return_value = []

        path = load_dump.download_dump("http://example.com/dump.tar.xz")
        os.unlink(path)

        mock_get.return_value.raise_for_status.assert_called_once()


# ---------------------------------------------------------------------------
# upload_chunk
# ---------------------------------------------------------------------------

class TestUploadChunk:
    def test_uploads_joined_lines_with_trailing_newline(self):
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob

        lines = ['{"a":1}', '{"a":2}']
        load_dump.upload_chunk(lines, mock_bucket, 0, "20260318-001000")

        mock_blob.upload_from_string.assert_called_once_with(
            '{"a":1}\n{"a":2}\n',
            content_type="application/jsonl",
        )

    def test_blob_name_uses_entity_chunk_and_date(self):
        mock_bucket = MagicMock()

        load_dump.upload_chunk(["line"], mock_bucket, 3, "20260318-001000")

        mock_bucket.blob.assert_called_once_with(
            "mb-dump/event/20260318-001000/event_003.jsonl"
        )


# ---------------------------------------------------------------------------
# extract_and_upload
# ---------------------------------------------------------------------------

class TestExtractAndUpload:
    @patch("scripts.load_dump.upload_chunk")
    @patch("scripts.load_dump.storage.Client")
    def test_extracts_lines_and_uploads(self, mock_client, mock_upload, sample_json_lines, monkeypatch):
        # Use a tiny chunk size so each line triggers its own chunk.
        monkeypatch.setattr(load_dump, "CHUNK_SIZE", 1)

        archive_bytes = _make_tar_xz("event", sample_json_lines)
        tmp = tempfile.NamedTemporaryFile(suffix=".tar.xz", delete=False)
        tmp.write(archive_bytes)
        tmp.close()

        try:
            total = load_dump.extract_and_upload(tmp.name, "20260318-001000")
        finally:
            os.unlink(tmp.name)

        assert total == 3
        assert mock_upload.call_count == 3

    @patch("scripts.load_dump.upload_chunk")
    @patch("scripts.load_dump.storage.Client")
    def test_single_chunk_when_size_is_large(self, mock_client, mock_upload, sample_json_lines, monkeypatch):
        monkeypatch.setattr(load_dump, "CHUNK_SIZE", 100 * 1024 * 1024)

        archive_bytes = _make_tar_xz("event", sample_json_lines)
        tmp = tempfile.NamedTemporaryFile(suffix=".tar.xz", delete=False)
        tmp.write(archive_bytes)
        tmp.close()

        try:
            total = load_dump.extract_and_upload(tmp.name, "20260318-001000")
        finally:
            os.unlink(tmp.name)

        assert total == 3
        assert mock_upload.call_count == 1

    @patch("scripts.load_dump.upload_chunk")
    @patch("scripts.load_dump.storage.Client")
    def test_returns_zero_when_member_not_found(self, mock_client, mock_upload):
        # Create archive with wrong member name.
        archive_bytes = _make_tar_xz("wrong_entity", ['{"id":"1"}'])
        tmp = tempfile.NamedTemporaryFile(suffix=".tar.xz", delete=False)
        tmp.write(archive_bytes)
        tmp.close()

        try:
            total = load_dump.extract_and_upload(tmp.name, "20260318-001000")
        finally:
            os.unlink(tmp.name)

        assert total == 0
        mock_upload.assert_not_called()


# ---------------------------------------------------------------------------
# load_to_bigquery
# ---------------------------------------------------------------------------

class TestLoadToBigquery:
    @patch("scripts.load_dump.bigquery.Client")
    def test_loads_from_correct_uri(self, mock_bq_class, monkeypatch):
        monkeypatch.setattr(load_dump, "BQ_PROJECT", "proj")
        mock_client = mock_bq_class.return_value
        mock_table = MagicMock()
        mock_table.num_rows = 100
        mock_client.get_table.return_value = mock_table

        load_dump.load_to_bigquery("20260318-001000", rows_uploaded=100)

        args, kwargs = mock_client.load_table_from_uri.call_args
        assert args[0] == "gs://is-rock-alive-landing/mb-dump/event/20260318-001000/*.jsonl"
        assert args[1] == "proj.raw.event_raw"

    @patch("scripts.load_dump.bigquery.Client")
    def test_uses_write_truncate(self, mock_bq_class, monkeypatch):
        monkeypatch.setattr(load_dump, "BQ_PROJECT", "proj")
        mock_client = mock_bq_class.return_value
        mock_table = MagicMock()
        mock_table.num_rows = 10
        mock_client.get_table.return_value = mock_table

        load_dump.load_to_bigquery("20260318-001000")

        _, kwargs = mock_client.load_table_from_uri.call_args
        job_config = kwargs["job_config"]
        assert job_config.write_disposition == "WRITE_TRUNCATE"

    @patch("scripts.load_dump.bigquery.Client")
    def test_runs_update_for_raw_loaded_at(self, mock_bq_class, monkeypatch):
        monkeypatch.setattr(load_dump, "BQ_PROJECT", "proj")
        mock_client = mock_bq_class.return_value
        mock_table = MagicMock()
        mock_table.num_rows = 5
        mock_client.get_table.return_value = mock_table

        load_dump.load_to_bigquery("20260318-001000")

        update_call = mock_client.query.call_args
        sql = update_call[0][0]
        assert "UPDATE" in sql
        assert "_raw_loaded_at" in sql
        assert "CURRENT_TIMESTAMP()" in sql

    @patch("scripts.load_dump.bigquery.Client")
    def test_logs_warning_on_row_count_mismatch(self, mock_bq_class, monkeypatch, caplog):
        monkeypatch.setattr(load_dump, "BQ_PROJECT", "proj")
        mock_client = mock_bq_class.return_value
        mock_table = MagicMock()
        mock_table.num_rows = 99
        mock_client.get_table.return_value = mock_table

        import logging
        with caplog.at_level(logging.WARNING):
            load_dump.load_to_bigquery("20260318-001000", rows_uploaded=100)

        assert any("mismatch" in r.message.lower() for r in caplog.records)

    @patch("scripts.load_dump.bigquery.Client")
    def test_no_warning_when_counts_match(self, mock_bq_class, monkeypatch, caplog):
        monkeypatch.setattr(load_dump, "BQ_PROJECT", "proj")
        mock_client = mock_bq_class.return_value
        mock_table = MagicMock()
        mock_table.num_rows = 100
        mock_client.get_table.return_value = mock_table

        import logging
        with caplog.at_level(logging.WARNING):
            load_dump.load_to_bigquery("20260318-001000", rows_uploaded=100)

        assert not any("mismatch" in r.message.lower() for r in caplog.records)

    @patch("scripts.load_dump.bigquery.Client")
    def test_clustering_fields(self, mock_bq_class, monkeypatch):
        monkeypatch.setattr(load_dump, "BQ_PROJECT", "proj")
        mock_client = mock_bq_class.return_value
        mock_table = MagicMock()
        mock_table.num_rows = 1
        mock_client.get_table.return_value = mock_table

        load_dump.load_to_bigquery("20260318-001000")

        _, kwargs = mock_client.load_table_from_uri.call_args
        job_config = kwargs["job_config"]
        assert job_config.clustering_fields == ["_source_system", "_raw_loaded_at"]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

class TestMain:
    @patch("scripts.load_dump.load_to_bigquery")
    @patch("scripts.load_dump.extract_and_upload", return_value=50)
    @patch("scripts.load_dump.download_dump", return_value="/tmp/fake.tar.xz")
    @patch("scripts.load_dump.check_blobs_exist", return_value=False)
    @patch("scripts.load_dump.get_latest_dump_date", return_value="20260318-001000")
    def test_full_flow_when_no_existing_blobs(
        self, mock_date, mock_exists, mock_download, mock_extract, mock_load
    ):
        with patch("os.unlink"):
            load_dump.main()

        mock_download.assert_called_once()
        mock_extract.assert_called_once_with("/tmp/fake.tar.xz", "20260318-001000")
        mock_load.assert_called_once_with("20260318-001000", 50)

    @patch("scripts.load_dump.load_to_bigquery")
    @patch("scripts.load_dump.extract_and_upload")
    @patch("scripts.load_dump.download_dump")
    @patch("scripts.load_dump.check_blobs_exist", return_value=True)
    @patch("scripts.load_dump.get_latest_dump_date", return_value="20260318-001000")
    def test_skips_download_when_blobs_exist(
        self, mock_date, mock_exists, mock_download, mock_extract, mock_load
    ):
        load_dump.main()

        mock_download.assert_not_called()
        mock_extract.assert_not_called()
        mock_load.assert_called_once_with("20260318-001000", None)

    @patch("scripts.load_dump.load_to_bigquery")
    @patch("scripts.load_dump.extract_and_upload", side_effect=RuntimeError("extract failed"))
    @patch("scripts.load_dump.download_dump", return_value="/tmp/fake.tar.xz")
    @patch("scripts.load_dump.check_blobs_exist", return_value=False)
    @patch("scripts.load_dump.get_latest_dump_date", return_value="20260318-001000")
    def test_cleans_up_temp_file_on_extract_failure(
        self, mock_date, mock_exists, mock_download, mock_extract, mock_load
    ):
        with patch("os.unlink") as mock_unlink:
            with pytest.raises(RuntimeError, match="extract failed"):
                load_dump.main()

            mock_unlink.assert_called_once_with("/tmp/fake.tar.xz")
