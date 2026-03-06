"""Tests for the stream decompression module."""

import io
import json
import lzma
import tarfile

from is_rock_alive.ingestion.stream import _read_jsonl, stream_archive


def _create_tar_xz(tmp_path, members: dict[str, list[dict]]):
    """Create a tar.xz archive with JSONL files.

    Args:
        tmp_path: Directory where the archive will be written.
        members: Mapping of member paths to lists of JSON objects.

    Returns:
        Path to the created archive.
    """
    archive_path = tmp_path / "test.tar.xz"
    with lzma.open(archive_path, "wb") as xz_file:
        with tarfile.open(fileobj=xz_file, mode="w:") as tar:
            for name, records in members.items():
                content = "\n".join(json.dumps(r) for r in records).encode()
                info = tarfile.TarInfo(name=name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    return archive_path


class TestReadJsonl:
    def test_single_record(self):
        data = json.dumps({"id": 1}).encode() + b"\n"
        records = list(_read_jsonl(io.BytesIO(data), chunk_size=1024))
        assert records == [{"id": 1}]

    def test_multiple_records(self):
        lines = [json.dumps({"id": i}) for i in range(5)]
        data = "\n".join(lines).encode()
        records = list(_read_jsonl(io.BytesIO(data), chunk_size=1024))
        assert len(records) == 5
        assert records[0]["id"] == 0
        assert records[4]["id"] == 4

    def test_empty_lines_skipped(self):
        data = b'{"id": 1}\n\n\n{"id": 2}\n'
        records = list(_read_jsonl(io.BytesIO(data), chunk_size=1024))
        assert records == [{"id": 1}, {"id": 2}]

    def test_small_chunk_size(self):
        """Records are parsed correctly even when chunk_size splits lines."""
        lines = [json.dumps({"name": f"item_{i}"}) for i in range(3)]
        data = "\n".join(lines).encode()
        records = list(_read_jsonl(io.BytesIO(data), chunk_size=10))
        assert len(records) == 3

    def test_no_trailing_newline(self):
        data = b'{"id": 1}'
        records = list(_read_jsonl(io.BytesIO(data), chunk_size=1024))
        assert records == [{"id": 1}]


class TestStreamArchive:
    def test_reads_mbdump_files(self, tmp_path):
        records = [{"id": 1}, {"id": 2}]
        archive = _create_tar_xz(tmp_path, {"mbdump/artist": records})
        result = list(stream_archive(archive))
        assert result == records

    def test_ignores_non_mbdump_files(self, tmp_path):
        archive = _create_tar_xz(tmp_path, {
            "mbdump/artist": [{"id": 1}],
            "other/file": [{"id": 99}],
        })
        result = list(stream_archive(archive))
        assert result == [{"id": 1}]

    def test_empty_archive(self, tmp_path):
        archive = _create_tar_xz(tmp_path, {})
        result = list(stream_archive(archive))
        assert result == []
