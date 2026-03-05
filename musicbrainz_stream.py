"""Stream decompression of MusicBrainz JSON dump tar.xz archives."""

import json
import tarfile
from collections.abc import Iterator

import requests


class MusicBrainzDumpStream:
    """Stream and decompress a MusicBrainz JSON dump tar.xz archive.

    Download a tar.xz archive over HTTP, decompress it on the fly, and
    yield parsed JSON objects from every JSONL data file under the
    ``mbdump/`` directory inside the archive.

    The class is iterable, so it can be used directly as a dlt resource
    generator or consumed in any ``for`` loop.

    Args:
        url: Full URL to a MusicBrainz ``.tar.xz`` dump file.
        chunk_size: Number of bytes to read per iteration when parsing
            the JSONL content.  Defaults to 1 MB.

    Example::

        import dlt

        @dlt.resource(name="artist", write_disposition="replace")
        def artist_resource():
            stream = MusicBrainzDumpStream(
                "https://data.metabrainz.org/.../artist.tar.xz"
            )
            yield from stream
    """

    MBDUMP_PREFIX = "mbdump/"

    def __init__(self, url: str, chunk_size: int = 1024 * 1024) -> None:
        """Initialise the stream with a remote archive URL."""
        self.url = url
        self.chunk_size = chunk_size

    def __iter__(self) -> Iterator[dict]:
        """Iterate over every JSON record in the archive."""
        with requests.get(self.url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            resp.raw.decode_content = True

            with tarfile.open(fileobj=resp.raw, mode="r|xz") as tar:
                for member in tar:
                    if not member.isfile():
                        continue
                    if not member.name.startswith(self.MBDUMP_PREFIX):
                        continue

                    fileobj = tar.extractfile(member)
                    if fileobj is None:
                        continue

                    yield from self._read_jsonl(fileobj)

    def _read_jsonl(self, fileobj) -> Iterator[dict]:
        """Yield parsed JSON objects from a JSONL file-like object."""
        buf = b""
        while True:
            chunk = fileobj.read(self.chunk_size)
            if not chunk:
                break
            buf += chunk
            # Split on newlines and yield complete lines
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if line:
                    yield json.loads(line)
        # Handle last line without trailing newline
        buf = buf.strip()
        if buf:
            yield json.loads(buf)
