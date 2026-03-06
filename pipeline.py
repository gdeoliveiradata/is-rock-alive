"""dlt pipeline that loads MusicBrainz JSON dump data into DuckDB."""

import dlt

from latest_dump import LatestDump
from musicbrainz_stream import MusicBrainzDumpStream


@dlt.source
def musicbrainz(base_url: str):
    """dlt source for MusicBrainz JSON dump data."""
    if not base_url.endswith("/"):
        base_url += "/"

    @dlt.resource(write_disposition="replace")
    def artist():
        yield from MusicBrainzDumpStream(f"{base_url}artist.tar.xz")

    @dlt.resource(write_disposition="replace")
    def release_group():
        yield from MusicBrainzDumpStream(f"{base_url}release-group.tar.xz")

    @dlt.resource(write_disposition="replace")
    def event():
        yield from MusicBrainzDumpStream(f"{base_url}event.tar.xz")

    return [artist, release_group, event]


if __name__ == "__main__":
    base_url = LatestDump().url

    pipeline = dlt.pipeline(
        pipeline_name="musicbrainz",
        destination="duckdb",
        dataset_name="musicbrainz",
    )

    info = pipeline.run(musicbrainz(base_url))
    print(info)
