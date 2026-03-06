"""Integration tests for the latest dump URL resolver.

These tests make real HTTP requests to MusicBrainz servers.
Run with: uv run pytest -m integration
"""

import pytest
import requests

from is_rock_alive.ingestion.latest_dump import BASE_URL, resolve_latest_dump_url


pytestmark = pytest.mark.integration


class TestResolveLatestDumpUrl:
    @pytest.mark.timeout(15)
    def test_index_page_is_reachable(self):
        resp = requests.get(BASE_URL, timeout=10)
        assert resp.status_code == 200

    @pytest.mark.timeout(15)
    def test_index_page_contains_latest_is_link(self):
        resp = requests.get(BASE_URL, timeout=10)
        assert "latest-is-" in resp.text

    @pytest.mark.timeout(15)
    def test_resolved_url_is_valid(self):
        url = resolve_latest_dump_url()
        assert url.startswith(BASE_URL)
        # HEAD request to check the directory exists
        resp = requests.head(url, timeout=10, allow_redirects=True)
        assert resp.status_code == 200
