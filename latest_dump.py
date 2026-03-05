"""Resolve the URL of the latest MusicBrainz JSON dump."""

import re

import requests


class LatestDump:
    """Discover the latest MusicBrainz JSON dump directory URL.

    Fetches the dump index page and extracts the ``latest-is-<date>``
    link to build the full URL pointing to the most recent dump.

    Attributes:
        url: Full URL to the latest dump directory.
    """

    BASE_URL = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/"

    def __init__(self) -> None:
        self.url = self._resolve_latest_dump_url()

    def _resolve_latest_dump_url(self) -> str:
        """Fetch the index page and return the latest dump directory URL.

        Raises:
            requests.HTTPError: If the index page request fails.
            ValueError: If the ``latest-is-`` link cannot be found.
        """
        resp = requests.get(self.BASE_URL, timeout=30)
        resp.raise_for_status()

        match = re.search(r'href="latest-is-([^"]+)"', resp.text)
        if not match:
            raise ValueError(
                f"Could not find 'latest-is-' link at {self.BASE_URL}"
            )

        return f"{self.BASE_URL}{match.group(1)}"


if __name__ == "__main__":
    dump_url = LatestDump().url
    print(dump_url)