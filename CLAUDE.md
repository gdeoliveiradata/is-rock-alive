# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MusicBrainz data engineering project on GCP. Ingests music metadata (artists, release groups, labels, events, genres) from MusicBrainz JSONL dumps (initial bulk load) and the MusicBrainz API (daily incremental). Data flows through a GCS + BigQuery lakehouse, transformed with dbt into analytical models focused on tracking rock music trends over the years. Visualized in Looker Studio. This is a learning/portfolio project.

## Architecture

```
MusicBrainz Dump (tar.xz/JSONL) --> [bulk_load.py on Cloud Run Job] --> GCS Landing Bucket --> BigQuery (raw)
MusicBrainz API (daily incremental) --> [dlt on Cloud Run Job] --> GCS Landing Bucket --> BigQuery (raw)
BigQuery (raw) --> dbt (on Airflow VM) --> staging --> trusted --> semantic --> Looker Studio
Orchestration: Airflow on GCE VM (e2-small, scheduling + dbt execution)
Ingestion compute: Cloud Run Jobs (source-based deployment via gcloud)
Infrastructure: Terraform
CI/CD: GitHub Actions
```

## Tech Stack

- **Cloud**: GCP (us-central1)
- **IaC**: Terraform
- **Storage**: GCS (raw files, permanent archive) + BigQuery (warehouse)
- **Transformation**: dbt-core + dbt-bigquery (runs on Airflow VM)
- **Orchestration**: Local Airflow (Docker Compose) for dev, GCE e2-small VM for production
- **Dashboards**: Looker Studio
- **CI/CD**: GitHub Actions
- **Language**: Python 3.10+, SQL

## Project Structure

```
terraform/          # GCP infrastructure (GCS, BigQuery, IAM, Airflow VM)
dbt/                # dbt project (models, tests, seeds, macros)
dags/               # Airflow DAGs (local Docker + GCE VM)
scripts/            # Python ingestion scripts (bulk load, incremental)
tests/              # Python unit tests
.github/workflows/  # CI/CD pipelines
```

## GCS Buckets and Path Structure

Two buckets (managed by Terraform):

- **`is-rock-alive-landing`** — permanent archive of all ingested data. Lifecycle rule transitions to Nearline after 30 days.
- **`is-rock-alive-pipeline`** — DAGs and scripts synced to the Airflow GCE VM.

Path layout within the landing bucket:
```
gs://is-rock-alive-landing/
  bulk/{entity}/{entity}_000.jsonl        # One-time dump load (e.g., bulk/event/event_000.jsonl)
  incremental/{entity}/{date}/{files}     # Daily API loads via dlt
  dlt-staging/                            # dlt temp files for BigQuery loads
```

**Why no separate staging bucket?** Originally provisioned but never used by any pipeline. Removed in the 2026-03-16 architecture review. dlt uses a `dlt-staging/` prefix within the landing bucket instead of a separate bucket.

## BigQuery Datasets

- `raw` — JSONL loads from GCS, fixed schema per table (`data` JSON + audit columns: `_source_file`, `_loaded_at`, `_batch_id`, `_source_system`, `_row_hash`), ingestion-time partitioned (`_PARTITIONTIME`)
- `staging` — dbt views: extract fields from `data` JSON column, type-cast, renamed columns, deduplicate
- `trusted` — dbt tables: deduplicated dimensions and facts (star schema)
- `semantic` — dbt tables: aggregated models for Looker Studio

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

# Bulk load (local)
ENTITY=event uv run python scripts/bulk_load.py

# Linting
sqlfluff lint dbt/models/       # SQL linting (BigQuery dialect)
ruff check scripts/ dags/       # Python linting

# Tests
pytest tests/
```

## Key Design Decisions

- **Reproducibility via Terraform**: Phase 0 is a minimal manual bootstrap (GCP account, project, APIs, Terraform SA). Everything else — pipeline SA, IAM bindings, GCS buckets, BigQuery datasets — is provisioned by `terraform apply`. Anyone cloning the repo can reproduce the full infrastructure.
- **Terraform SA is the only manual step**: The chicken-and-egg problem — Terraform needs a SA to authenticate, so it must be created via `gcloud` before Terraform runs. The pipeline SA and all its role bindings are managed by Terraform.
- **Additive IAM bindings**: Use `google_project_iam_member` (additive) in Terraform, not `google_project_iam_binding` or `google_project_iam_policy`. Avoids revoking permissions from the user account or Google-managed SAs.
- **No JSON key files**: SA key creation is disabled by org policy. Locally, authenticate via ADC (`gcloud auth application-default login`). In CI/CD, GitHub Actions uses Workload Identity Federation.
- **Cloud Run managed via `gcloud`, not Terraform**: Source-based deployment (`gcloud run jobs deploy --source`) builds and deploys in one step. Terraform can't do this.
- **Two ingestion approaches**: Bulk load (`bulk_load.py`) is a one-time dump load using `google-cloud-storage` + `google-cloud-bigquery`. Daily incremental uses dlt (pagination, rate limiting, watermarks). dbt owns all transformations.
- **Bulk load skip logic**: Checks if blobs already exist at `gs://landing/bulk/{entity}/`. If files exist, logs a message and exits cleanly (not an error). To rerun, manually delete the GCS files first. No force flag.
- **Bulk load uses `WRITE_TRUNCATE`**: Full table replace in BigQuery for idempotency.
- **Incremental uses `WRITE_APPEND`**: Raw tables are append-only, dbt staging deduplicates by latest record per MBID.
- **Ingestion-time partitioning on raw tables**: BigQuery adds `_PARTITIONTIME` automatically at load time. Provides a load timestamp without modifying the source data, and enables partition pruning on queries.
- **GCS landing bucket is a permanent archive**: Data stays in GCS as an immutable copy. If BigQuery loads fail or transformations have bugs, you can reprocess from the landing bucket.
- **dlt stages through GCS**: dlt uses `gs://landing/dlt-staging/` as a staging area before loading into BigQuery. This is why a separate staging bucket is not needed.
- **dbt runs on the Airflow VM**: The e2-small VM (2 vCPUs, 2 GB RAM) handles dbt fine — dbt compiles SQL and sends it to BigQuery, no heavy local processing. This avoids a separate Cloud Run Job for dbt and keeps the architecture simpler.
- **Schema-on-read raw layer**: Raw BigQuery tables use a fixed, entity-agnostic schema: `data` (JSON), `_source_file` (STRING), `_loaded_at` (TIMESTAMP), `_batch_id` (STRING), `_source_system` (STRING), `_row_hash` (STRING). No schema autodetect — all parsing and typing happens in dbt staging models via `JSON_VALUE`/`JSON_EXTRACT_ARRAY`. This decouples ingestion from schema management: upstream MusicBrainz schema changes don't break the load job, and all transformation logic lives in one place (dbt).
- **JSONL for raw layer**: Matches source format, BigQuery loads JSONL natively for free.
- **Genre via tags**: MusicBrainz has no genre field — genres come from the tag system. A `genre_mapping` dbt seed maps raw tags to standardized categories.
- **Region**: `us-central1` for all resources (GCS, BigQuery, Cloud Run, GCE). Same-region = free data transfer.

## Data Flow

1. **Bulk ingest (one-time)**: MusicBrainz tar.xz dump → `bulk_load.py` on Cloud Run → `gs://landing/bulk/{entity}/` → BigQuery `raw` (WRITE_TRUNCATE, fixed schema: `data` JSON + audit cols)
2. **Incremental ingest (daily)**: MusicBrainz API → dlt on Cloud Run → `gs://landing/incremental/{entity}/{date}/` → BigQuery `raw` (WRITE_APPEND, same fixed schema)
3. **Transform (dbt on Airflow VM)**:
   - `staging` (views) — extract fields from `data` JSON column, cast, rename, deduplicate (latest per MBID), 1:1 with raw tables
   - `trusted` (tables) — star schema: dims (artists, release_groups, labels, events, genres) + facts + bridges
   - `semantic` (tables) — pre-aggregated for dashboards (rock trends by year/subgenre/label)
4. **Serve**: BigQuery `semantic` → Looker Studio dashboards

## Orchestration

**Daily Airflow DAG** (runs on GCE VM):
1. `CloudRunExecuteJobOperator` → trigger dlt incremental ingest on Cloud Run
2. `BashOperator` → `dbt run` (locally on VM)
3. `BashOperator` → `dbt test` (locally on VM)

**Initial load DAG** (manual, one-time): triggers bulk_load.py Cloud Run Job per entity, then full dbt run.

## MusicBrainz API Notes

- Rate limit: 1 request/second — always include a custom User-Agent header
- Entity IDs are MBIDs (UUIDs) — use these as primary keys throughout
- Genres are derived from the tag system, not a dedicated genre field
- A `genre_mapping` dbt seed maps raw tags to standardized genre categories

## User Context

- This is a learning/portfolio project — the user is a GCP/data engineering beginner
- See `ROADMAP.md` for the full phased implementation plan with study references
- **Teaching approach**: Explain concepts, provide references/docs, and describe *how* to do things — but do NOT give ready-made answers (commands, code, configs) upfront. The user wants to learn by figuring it out themselves, not by copying output. Only give direct answers when explicitly asked for them.
