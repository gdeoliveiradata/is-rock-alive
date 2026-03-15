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
Ingestion compute: Cloud Run Jobs (source-based deployment via gcloud, up to 32 GiB RAM, pay-per-use)
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
terraform/          # GCP infrastructure (GCS, BigQuery, IAM, Airflow VM)
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

## Key Design Decisions

- **Reproducibility via Terraform**: Phase 0 is a minimal manual bootstrap (GCP account, project, APIs, Terraform SA). Everything else — pipeline SA, IAM bindings, GCS buckets, BigQuery datasets — is provisioned by `terraform apply`. Anyone cloning the repo can reproduce the full infrastructure.
- **Terraform SA is the only manual step**: The chicken-and-egg problem — Terraform needs a SA to authenticate, so it must be created via `gcloud` before Terraform runs. The pipeline SA and all its role bindings are managed by Terraform.
- **Additive IAM bindings**: Use `google_project_iam_member` (additive) in Terraform, not `google_project_iam_binding` (authoritative per role) or `google_project_iam_policy` (fully authoritative). This avoids accidentally revoking permissions from the user account or Google-managed SAs.
- **No JSON key files**: SA key creation is disabled by org policy. Locally, Terraform and tools authenticate via Application Default Credentials (`gcloud auth application-default login`). In CI/CD, GitHub Actions uses Workload Identity Federation.
- **Cloud Run managed via `gcloud`, not Terraform**: Source-based deployment (`gcloud run jobs deploy --source`) creates the job and builds the container image in one step. Terraform can't do this. `gcloud run jobs deploy` is an upsert (creates or updates).
- **Two ingestion approaches**: Initial bulk load uses simple Python scripts (`google-cloud-storage` + `google-cloud-bigquery`) — no dlt, since it's a one-time operation. Daily incremental API loads use dlt, with normalization disabled (dbt owns all transformations).
- **Append-only raw layer**: Raw tables use WRITE_APPEND, deduplication on MBIDs happens in dbt staging.
- **JSONL for raw layer**: Matches the source format, schema-on-read avoids Parquet merge issues, BigQuery loads JSONL natively for free.
- **Genre via tags**: MusicBrainz has no genre field — genres come from the tag system. A `genre_mapping` dbt seed maps raw tags to standardized categories.
- **Region**: `us-central1` for both compute and BigQuery datasets (same region as GCS buckets, free data transfer).

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

## User Context

- This is a learning project — the user is a GCP/data engineering beginner
- See `ROADMAP.md` for the full phased implementation plan with study references
- **Teaching approach**: Explain concepts, provide references/docs, and describe *how* to do things — but do NOT give ready-made answers (commands, code, configs) upfront. The user wants to learn by figuring it out themselves, not by copying output. Only give direct answers when explicitly asked for them.
