import requests


DUMP_BASE_URL = "https://data.metabrainz.org/pub/musicbrainz/data/json-dumps"

HTTP_TIMEOUT = 30 # seconds timeout for the initial connection


def get_latest_dump_date() -> str:
    """Fetch the latest MusicBrainz JSON dump date from the mirror server.

    Reads the LATEST file from data.metabrainz.org, which contains the
    date string of the most recent available dump.

    Returns:
        The dump date as a string (e.g. '20260315-001000').

    Raises:
        requests.HTTPError: If the server returns a non-2xx response.
    """
    resp = requests.get(f"{DUMP_BASE_URL}/LATEST", timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.text.split()[0]


def main() -> None:
    date = get_latest_dump_date() 
    print(f"{DUMP_BASE_URL}/{date}")


if __name__ == "__main__":
    main()