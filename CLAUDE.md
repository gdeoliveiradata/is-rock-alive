# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**is-rock-alive** is a Python project that ingests MusicBrainz JSON dump data. It downloads, stream-decompresses, and parses MusicBrainz `.tar.xz` dump archives into JSON records, intended for use as a dlt (data load tool) resource.

## Setup

- Python 3.14+, managed with `uv`
- Virtual environment: `.venv/` (already created)
- Install dependencies: `uv sync`
- Dependencies: `requests`, `dlt[duckdb]`

## Running

```bash
# Discover latest dump URL
uv run python latest_dump.py

# Run the full dlt pipeline (loads artist, release_group, event into DuckDB)
uv run python pipeline.py
```

## Architecture

Three standalone modules (no package structure):

- **`latest_dump.py`** — `LatestDump` class that scrapes the MusicBrainz dump index page to resolve the URL of the latest `json-dumps` directory. Parses the `latest-is-<date>` link from the HTML.

- **`musicbrainz_stream.py`** — `MusicBrainzDumpStream` class that streams a `.tar.xz` archive over HTTP, decompresses on the fly via `tarfile`, and yields parsed JSON objects from JSONL files under `mbdump/`. Designed as an iterable to plug directly into a dlt `@dlt.resource` generator.

- **`pipeline.py`** — dlt pipeline script. Defines a `@dlt.source` named `musicbrainz` with three `@dlt.resource` functions (`artist`, `release_group`, `event`), each streaming its corresponding dump archive. Loads into a local DuckDB database with `write_disposition="replace"`.

## Data Source

MusicBrainz JSON dumps are hosted at `https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/`. Archives contain JSONL files under a `mbdump/` prefix inside the tar.
