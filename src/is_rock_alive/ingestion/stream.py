"""Stream decompression of MusicBrainz JSON dump tar.xz archives."""

import json
import tarfile
from collections.abc import Iterator
from pathlib import Path


MBDUMP_PREFIX = "mbdump/"


def stream_archive(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[dict]:
    """Open a local MusicBrainz tar.xz archive and yield parsed JSON records.

    Decompresses the archive and reads every JSONL file under the
    ``mbdump/`` directory, yielding one dict per line.

    Args:
        path: Path to a local ``.tar.xz`` dump file.
        chunk_size: Bytes to read per iteration when parsing JSONL content.

    Yields:
        Parsed JSON objects from the archive.
    """
    with tarfile.open(path, mode="r:xz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            if not member.name.startswith(MBDUMP_PREFIX):
                continue

            fileobj = tar.extractfile(member)
            if fileobj is None:
                continue

            yield from _read_jsonl(fileobj, chunk_size)


def _read_jsonl(fileobj, chunk_size: int) -> Iterator[dict]:
    """Yield parsed JSON objects from a JSONL file-like object."""
    buf = b""
    while True:
        chunk = fileobj.read(chunk_size)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if line:
                yield json.loads(line)
    buf = buf.strip()
    if buf:
        yield json.loads(buf)
