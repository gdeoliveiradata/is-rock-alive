"""Download MusicBrainz JSON dump archives to the landing directory."""

from pathlib import Path

import requests
from tqdm import tqdm

from is_rock_alive.ingestion.latest_dump import resolve_latest_dump_url

ARCHIVES = ["artist", "release-group", "event"]


def download_archives(landing_dir: Path) -> list[Path]:
    """Download MusicBrainz tar.xz archives to the landing directory.

    Args:
        landing_dir: Directory where archives will be saved.

    Returns:
        List of paths to downloaded (or already existing) archive files.
    """
    base_url = resolve_latest_dump_url()
    if not base_url.endswith("/"):
        base_url += "/"

    landing_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []

    for name in ARCHIVES:
        filename = f"{name}.tar.xz"
        dest = landing_dir / filename

        if dest.exists():
            print(f"  Skipping {filename} (already downloaded)")
            downloaded.append(dest)
            continue

        url = f"{base_url}{filename}"
        print(f"  Downloading {filename}...")

        with requests.get(url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))

            with open(dest, "wb") as f, tqdm(
                total=total, unit="B", unit_scale=True, desc=filename
            ) as bar:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
                    bar.update(len(chunk))

        downloaded.append(dest)

    return downloaded


if __name__ == "__main__":
    landing = Path("data/landing")
    paths = download_archives(landing)
    print(f"Done. {len(paths)} archive(s) ready in {landing}")
