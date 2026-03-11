# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MusicBrainz data engineering project on GCP. Ingests music metadata (artists, release groups, labels, events, genres) from MusicBrainz JSONL dumps (initial bulk load) and the MusicBrainz API (daily incremental). Data flows through a GCS + BigQuery lakehouse, transformed with dbt into analytics models focused on tracking rock music trends over the years. Visualized in Looker Studio.

## Architecture

```
MusicBrainz Dump (tar.xz/JSONL) --> [Python scripts on Cloud Run Job] --> GCS Raw Bucket --> BigQuery (raw)
MusicBrainz API (daily incremental) --> [dlt on Cloud Run Job] --> GCS Raw Bucket --> BigQuery (raw)
BigQuery (raw) --> dbt staging --> dbt curated --> dbt analytics --> Looker Studio
Orchestration: Airflow on GCE VM (e2-small, scheduling only)
Ingestion compute: Cloud Run Jobs (up to 32 GB RAM, pay-per-use)
Container images: Artifact Registry
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

- **No JSON key files**: SA key creation is disabled by org policy (`constraints/iam.disableServiceAccountKeyCreation`). Locally, Terraform and other tools authenticate via Application Default Credentials (`gcloud auth application-default login`). In CI/CD, GitHub Actions uses Workload Identity Federation to impersonate the Terraform SA with short-lived tokens.
- **Local Airflow for dev, GCE VM for prod**: Docker Compose for development; GCE e2-small VM for production scheduling (scheduling only — no heavy compute). VM kept stopped when idle to save costs (~$1-2/mo disk-only vs. ~$15-30/mo always-on); started manually (`gcloud compute instances start`) or via GCE instance schedule for pipeline windows
- **Two ingestion approaches, both on Cloud Run**: Initial bulk load uses simple Python scripts (`google-cloud-storage` + `google-cloud-bigquery`) — no dlt, since it's a one-time operation. Daily incremental API loads use dlt. Both run as Cloud Run Jobs (up to 32 GB RAM, pay-per-use) for fast network and consistent deployment. Airflow triggers Cloud Run jobs via `CloudRunExecuteJobOperator`. Container images stored in Artifact Registry
- **Append-only raw layer**: raw tables use WRITE_APPEND, deduplication on MBIDs happens in dbt staging
- **Watermark-based incrementals**: track last sync timestamp per entity, API pulls only new/updated records
- **Genre via tags**: MusicBrainz has no genre field — genres come from the tag system. A `genre_mapping` dbt seed maps raw tags (e.g., "hard rock", "classic rock") to standardized categories
- **JSONL for raw layer**: Raw GCS files stay in JSONL (source format). Schema-on-read avoids Parquet schema merge issues across files, and BigQuery loads JSONL natively for free. Parquet is better suited for curated/analytics layers.
- **dlt normalization disabled**: dlt normalization is disabled for the incremental pipeline — raw data lands as-is, and dbt owns all transformation logic in the staging layer. This avoids splitting transformation across two tools.
- **Region**: `us-central1` for cost; BigQuery dataset in `US` multi-region for free GCS transfer

## User Context

- This is a learning project — the user is a GCP/data engineering beginner
- See `ROADMAP.md` for the full phased implementation plan with study references
- **Teaching approach**: Explain concepts, provide references/docs, and describe *how* to do things — but do NOT give ready-made answers (commands, code, configs) upfront. The user wants to learn by figuring it out themselves, not by copying output. Only give direct answers when explicitly asked for them.
