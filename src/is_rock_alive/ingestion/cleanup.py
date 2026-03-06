"""Clean up landing archives after successful bronze layer load."""

from pathlib import Path

LANDING_DIR = Path("data/landing")
BRONZE_DIR = Path("data/bronze")

RESOURCES = ["artist", "release_group", "event"]


def _bronze_has_data(bronze_dir: Path, resource_name: str) -> bool:
    """Check whether at least one Parquet file exists for a resource."""
    pattern = f"**/{resource_name}/**/*.parquet"
    return any(bronze_dir.glob(pattern))


def cleanup_landing(
    landing_dir: Path = LANDING_DIR,
    bronze_dir: Path = BRONZE_DIR,
) -> list[Path]:
    """Delete landing tar.xz files whose bronze Parquet output exists.

    For each resource, checks that ``bronze_dir`` contains at least one
    Parquet file before removing the corresponding archive from
    ``landing_dir``.

    Args:
        landing_dir: Directory containing the tar.xz archives.
        bronze_dir: Directory containing the bronze Parquet files.

    Returns:
        List of deleted archive paths.
    """
    # Map resource names to their archive filenames
    archive_map = {
        "artist": "artist.tar.xz",
        "release_group": "release-group.tar.xz",
        "event": "event.tar.xz",
    }

    deleted: list[Path] = []

    for resource_name, archive_name in archive_map.items():
        archive_path = landing_dir / archive_name
        if not archive_path.exists():
            continue

        if _bronze_has_data(bronze_dir, resource_name):
            archive_path.unlink()
            print(f"  Deleted {archive_path}")
            deleted.append(archive_path)
        else:
            print(f"  Keeping {archive_path} (no bronze data found for {resource_name})")

    return deleted


if __name__ == "__main__":
    deleted = cleanup_landing()
    print(f"Cleaned up {len(deleted)} archive(s).")
