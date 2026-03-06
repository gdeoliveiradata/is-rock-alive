"""Resolve the URL of the latest MusicBrainz JSON dump."""

import re

import requests

BASE_URL = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/"


def resolve_latest_dump_url() -> str:
    """Fetch the MusicBrainz dump index page and return the latest dump URL.

    Returns:
        Full URL to the latest dump directory.

    Raises:
        requests.HTTPError: If the index page request fails.
        ValueError: If the ``latest-is-`` link cannot be found.
    """
    resp = requests.get(BASE_URL, timeout=30)
    resp.raise_for_status()

    match = re.search(r'href="latest-is-([^"]+)"', resp.text)
    if not match:
        raise ValueError(f"Could not find 'latest-is-' link at {BASE_URL}")

    return f"{BASE_URL}{match.group(1)}"


if __name__ == "__main__":
    print(resolve_latest_dump_url())
