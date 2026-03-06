"""Tests for the landing cleanup module."""

from is_rock_alive.ingestion.cleanup import cleanup_landing


def _setup_dirs(tmp_path):
    landing = tmp_path / "landing"
    bronze = tmp_path / "bronze"
    landing.mkdir()
    bronze.mkdir()
    return landing, bronze


def _create_archive(landing, name):
    path = landing / name
    path.write_bytes(b"fake archive content")
    return path


def _create_parquet(bronze, resource_name):
    parquet_dir = bronze / "musicbrainz" / resource_name
    parquet_dir.mkdir(parents=True)
    (parquet_dir / "part_0.parquet").write_bytes(b"fake parquet")


class TestCleanupLanding:
    def test_deletes_when_bronze_exists(self, tmp_path):
        landing, bronze = _setup_dirs(tmp_path)
        _create_archive(landing, "artist.tar.xz")
        _create_parquet(bronze, "artist")

        deleted = cleanup_landing(landing, bronze)

        assert len(deleted) == 1
        assert not (landing / "artist.tar.xz").exists()

    def test_keeps_when_no_bronze_data(self, tmp_path):
        landing, bronze = _setup_dirs(tmp_path)
        _create_archive(landing, "artist.tar.xz")

        deleted = cleanup_landing(landing, bronze)

        assert deleted == []
        assert (landing / "artist.tar.xz").exists()

    def test_skips_missing_archives(self, tmp_path):
        landing, bronze = _setup_dirs(tmp_path)
        _create_parquet(bronze, "artist")

        deleted = cleanup_landing(landing, bronze)

        assert deleted == []

    def test_partial_cleanup(self, tmp_path):
        """Only deletes archives whose bronze output exists."""
        landing, bronze = _setup_dirs(tmp_path)
        _create_archive(landing, "artist.tar.xz")
        _create_archive(landing, "release-group.tar.xz")
        _create_archive(landing, "event.tar.xz")
        _create_parquet(bronze, "artist")
        _create_parquet(bronze, "event")

        deleted = cleanup_landing(landing, bronze)

        assert len(deleted) == 2
        assert not (landing / "artist.tar.xz").exists()
        assert (landing / "release-group.tar.xz").exists()
        assert not (landing / "event.tar.xz").exists()
