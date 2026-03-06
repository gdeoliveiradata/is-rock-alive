"""dlt pipeline that loads MusicBrainz JSON dumps into Parquet (bronze layer)."""

from pathlib import Path

import dlt

from is_rock_alive.ingestion.stream import stream_archive

LANDING_DIR = Path("data/landing")
BRONZE_DIR = "data/bronze"


@dlt.source
def musicbrainz(landing_dir: Path = LANDING_DIR):
    """dlt source reading MusicBrainz data from local tar.xz archives."""

    @dlt.resource(write_disposition="replace")
    def artist():
        yield from stream_archive(landing_dir / "artist.tar.xz")

    @dlt.resource(write_disposition="replace")
    def release_group():
        yield from stream_archive(landing_dir / "release-group.tar.xz")

    @dlt.resource(write_disposition="replace")
    def event():
        yield from stream_archive(landing_dir / "event.tar.xz")

    return [artist, release_group, event]


def run_pipeline(
    landing_dir: Path = LANDING_DIR,
    bronze_dir: str = BRONZE_DIR,
) -> dlt.pipeline.SupportsPipeline:
    """Create and run the MusicBrainz dlt pipeline.

    Args:
        landing_dir: Directory containing the downloaded tar.xz archives.
        bronze_dir: Directory where Parquet files will be written.

    Returns:
        The pipeline load info.
    """
    pipeline = dlt.pipeline(
        pipeline_name="musicbrainz",
        destination=dlt.destinations.filesystem(bronze_dir),
        dataset_name="musicbrainz",
        progress="tqdm",
    )

    pipeline.drop()
    return pipeline.run(musicbrainz(landing_dir), loader_file_format="parquet")


if __name__ == "__main__":
    info = run_pipeline()
    print(info)
