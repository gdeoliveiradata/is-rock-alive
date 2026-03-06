"""Integration tests for the download module.

Verifies that MusicBrainz archive URLs are valid without downloading full files.
Run with: uv run pytest -m integration
"""

import pytest
import requests

from is_rock_alive.ingestion.download import ARCHIVES
from is_rock_alive.ingestion.latest_dump import resolve_latest_dump_url


pytestmark = pytest.mark.integration


class TestArchiveUrlsExist:
    @pytest.fixture(scope="class")
    def base_url(self):
        url = resolve_latest_dump_url()
        if not url.endswith("/"):
            url += "/"
        return url

    @pytest.mark.timeout(15)
    @pytest.mark.parametrize("archive_name", ARCHIVES)
    def test_archive_url_returns_200(self, base_url, archive_name):
        """HEAD request to verify each archive URL exists (no full download)."""
        url = f"{base_url}{archive_name}.tar.xz"
        resp = requests.head(url, timeout=10, allow_redirects=True)
        assert resp.status_code == 200, f"{url} returned {resp.status_code}"

    @pytest.mark.timeout(15)
    @pytest.mark.parametrize("archive_name", ARCHIVES)
    def test_archive_has_content_length(self, base_url, archive_name):
        """Verify archives report a non-zero content-length."""
        url = f"{base_url}{archive_name}.tar.xz"
        resp = requests.head(url, timeout=10, allow_redirects=True)
        content_length = int(resp.headers.get("content-length", 0))
        assert content_length > 0, f"{url} has no content-length header"
