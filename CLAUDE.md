# CLAUDE.md

## Project Overview

**is-rock-alive** is a data engineering portfolio project that answers "Is rock alive?" by analyzing MusicBrainz data — tracking rock releases over time, active artists, and events.

## Stack

- **Ingestion**: dlt (data load tool) writing Parquet files
- **Storage**: MinIO (local folders during development)
- **Processing**: DuckDB + dbt (medallion lakehouse: bronze → silver → gold)
- **Dashboards**: Apache Superset
- **Orchestration**: Apache Airflow (manual triggers only)
- **Infrastructure**: Docker Compose
- **Language**: Python 3.14+, managed with uv

## Setup

```bash
uv sync                    # install dependencies
uv sync --extra dev        # install with test dependencies
```

## Running the Ingestion Pipeline

```bash
# Step 1: Download archives to data/landing/
uv run python -m is_rock_alive.ingestion.download

# Step 2: Load into Parquet files in data/bronze/
uv run python -m is_rock_alive.ingestion.pipeline

# Step 3: Clean up landing archives (only deletes if bronze data exists)
uv run python -m is_rock_alive.ingestion.cleanup
```

## Running Tests

```bash
uv run pytest                         # unit tests only
uv run pytest -m integration          # integration tests (requires network)
uv run pytest -m "not integration"    # skip integration tests
```

## Project Structure

```
is-rock-alive/
├── src/is_rock_alive/          # Main Python package
│   └── ingestion/              # Ingestion layer (dlt pipeline)
│       ├── latest_dump.py      # Resolve latest MusicBrainz dump URL
│       ├── download.py         # Download tar.xz archives to landing
│       ├── stream.py           # Stream-decompress archives, yield JSON
│       ├── pipeline.py         # dlt source/pipeline definition
│       └── cleanup.py          # Delete landing files after bronze load
├── tests/ingestion/            # Tests for ingestion modules
├── dags/                       # Airflow DAGs (future)
├── dbt/                        # dbt project (future)
├── docker/                     # Dockerfiles (future)
├── data/
│   ├── landing/                # Downloaded tar.xz archives
│   ├── bronze/                 # Raw Parquet from dlt (full replace)
│   ├── silver/                 # Cleaned/transformed (future, dbt)
│   └── gold/                   # Modeled/aggregated (future, dbt)
├── .dlt/config.toml            # dlt config (tuned for 5GB RAM)
├── docker-compose.yml          # Docker Compose (future)
└── pyproject.toml
```

## Architecture

### Medallion Lakehouse

- **Landing**: Raw tar.xz archives downloaded from MusicBrainz
- **Bronze**: Raw Parquet files produced by dlt (full replace each run)
- **Silver**: Cleaned and typed data (future — dbt + DuckDB)
- **Gold**: Aggregated analytics tables (future — dbt + DuckDB)

### Ingestion Design

Each module exposes a callable function (not just a script), making them composable as Airflow tasks. The `__main__` blocks allow manual execution.

MusicBrainz entities ingested: `artist`, `release_group`, `event`.

Data source: `https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/`

### Performance

`.dlt/config.toml` tunes the pipeline for 5GB RAM:
- Extract/normalize file rotation: 50k items / 1MB per file
- 2 parallel normalize workers

## Conventions

- All functions accept paths as parameters (no hardcoded globals) for testability
- Integration tests (HTTP calls) are marked with `pytest.mark.integration`
- Data directories are gitignored; structure preserved via `.gitkeep` files
