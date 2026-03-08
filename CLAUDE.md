# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MusicBrainz data engineering project on GCP. Ingests music metadata (artists, release groups, labels, events, genres) from MusicBrainz JSONL dumps (initial bulk load) and the MusicBrainz API (daily incremental). Data flows through a GCS + BigQuery lakehouse, transformed with dbt into analytics models focused on tracking rock music trends over the years. Visualized in Looker Studio.

## Architecture

```
MusicBrainz Dump (tar.xz/JSONL) --> GCS Raw Bucket --> BigQuery (raw)
MusicBrainz API (daily incremental) --> GCS Raw Bucket --> BigQuery (raw)
BigQuery (raw) --> dbt staging --> dbt curated --> dbt analytics --> Looker Studio
Orchestration: Airflow on GCE VM (e2-small)
Infrastructure: Terraform
CI/CD: GitHub Actions
```

## Tech Stack

- **Cloud**: GCP (us-central1)
- **IaC**: Terraform
- **Storage**: GCS (raw files) + BigQuery (warehouse)
- **Transformation**: dbt-core + dbt-bigquery
- **Orchestration**: Local Airflow (Docker Compose) for dev, GCE e2-small VM for production
- **Dashboards**: Looker Studio
- **CI/CD**: GitHub Actions
- **Language**: Python 3.10+, SQL

## Project Structure

```
terraform/          # All GCP infrastructure
dbt/                # dbt project (models, tests, seeds, macros)
dags/               # Airflow DAGs (local Docker + GCE VM)
scripts/            # Python ingestion scripts (upload, bulk load, incremental)
tests/              # Python unit tests
.github/workflows/  # CI/CD pipelines
```

## BigQuery Datasets

- `raw` — direct loads from GCS JSONL files
- `staging` — dbt views: clean, type-cast, renamed columns
- `curated` — dbt tables: deduplicated dimensions and facts
- `analytics` — dbt tables: aggregated models for Looker Studio

## Key Commands

```bash
# Terraform
cd terraform && terraform init
terraform plan
terraform apply

# dbt
cd dbt && dbt run --target dev
dbt test --target dev
dbt build --target dev          # run + test combined
dbt run --select staging        # run only staging models
dbt run --select analytics      # run only analytics models

# Linting
sqlfluff lint dbt/models/       # SQL linting (BigQuery dialect)
ruff check scripts/ dags/       # Python linting

# Tests
pytest tests/
```

## MusicBrainz API Notes

- Rate limit: 1 request/second — always include a custom User-Agent header
- Entity IDs are MBIDs (UUIDs) — use these as primary keys throughout
- Genres are derived from the tag system, not a dedicated genre field
- A `genre_mapping` dbt seed maps raw tags to standardized genre categories

## Data Flow

1. **Ingest**: MusicBrainz tar.xz/JSONL dump (initial) + API (daily incremental) -> GCS raw bucket
2. **Load**: GCS JSONL -> BigQuery `raw` dataset (load jobs, free)
3. **Transform (dbt)**:
   - `staging` (views) — clean, cast, rename, 1:1 with raw tables
   - `curated` (tables) — deduplicate, join, star schema (dims + facts + bridges)
   - `analytics` (tables) — pre-aggregated for dashboards (rock trends by year/subgenre/label)
4. **Serve**: BigQuery `analytics` -> Looker Studio dashboards

## Key Design Decisions

- **Local Airflow for dev, GCE VM for prod**: Docker Compose for development; GCE e2-small VM (~$15-30/mo) for production scheduling
- **Append-only raw layer**: raw tables use WRITE_APPEND, deduplication on MBIDs happens in dbt staging
- **Watermark-based incrementals**: track last sync timestamp per entity, API pulls only new/updated records
- **Genre via tags**: MusicBrainz has no genre field — genres come from the tag system. A `genre_mapping` dbt seed maps raw tags (e.g., "hard rock", "classic rock") to standardized categories
- **Region**: `us-central1` for cost; BigQuery dataset in `US` multi-region for free GCS transfer

## User Context

- This is a learning project — the user is a GCP/data engineering beginner
- Prefer clear explanations over terse commands
- See `ROADMAP.md` for the full phased implementation plan with study references
