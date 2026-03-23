# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MusicBrainz data engineering project on GCP. Ingests music metadata (artists, release groups, labels, events, genres) from MusicBrainz JSONL dumps (initial bulk load) and the MusicBrainz API (daily incremental). Data flows through a GCS + BigQuery lakehouse, transformed with dbt into analytical models focused on tracking rock music trends over the years. Visualized in Looker Studio. This is a learning/portfolio project.

## Architecture

```
MusicBrainz Dump (tar.xz/JSONL) --> [load_dump.py on Cloud Run Job] --> GCS Landing Bucket --> BigQuery (raw)
MusicBrainz API (daily incremental) --> [dlt on Cloud Run Job] --> GCS Landing Bucket --> BigQuery (raw)
BigQuery (raw) --> dbt (on Airflow VM) --> staging --> trusted --> semantic --> Looker Studio
Orchestration: Airflow on GCE VM (e2-small, scheduling + dbt execution)
Ingestion compute: Cloud Run Jobs (Docker image built locally, deployed via gcloud)
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
terraform/          # GCP infrastructure (GCS, BigQuery, IAM, Artifact Registry, Airflow VM)
dbt/                # dbt project (models, tests, seeds, macros)
dags/               # Airflow DAGs (local Docker + GCE VM)
scripts/            # Python ingestion scripts (bulk load, incremental)
docker/             # Dockerfiles and build configs per image
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
  mb-dump/{entity}/{dump_date}/{entity}_000.jsonl   # One-time dump load (e.g., mb-dump/event/20260318-001001/event_000.jsonl)
  incremental/{entity}/{date}/{files}               # Daily API loads via dlt
  dlt-staging/                                      # dlt temp files for BigQuery loads
```

**Why no separate staging bucket?** Originally provisioned but never used by any pipeline. Removed in the 2026-03-16 architecture review. dlt uses a `dlt-staging/` prefix within the landing bucket instead of a separate bucket.

## BigQuery Datasets

- `raw` — JSONL loads from GCS, fixed schema per table (`json_data` JSON + audit columns: `_source_file`, `_source_system`, `_batch_id`, `_landing_loaded_at`, `_raw_loaded_at`). Raw JSON is wrapped with audit metadata at ingestion time; `_raw_loaded_at` is populated via post-load UPDATE. `_row_hash` is computed in dbt staging, not at ingestion.
- `staging` — dbt views: extract fields from `json_data` JSON column, type-cast, renamed columns, deduplicate
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
ENTITY=event uv run python scripts/load_dump.py

# Docker build, push, and deploy (Cloud Run)
docker build -f docker/load-dump/Dockerfile -t us-central1-docker.pkg.dev/is-rock-alive/cloud-run-images/load-dump .
docker push us-central1-docker.pkg.dev/is-rock-alive/cloud-run-images/load-dump
gcloud run jobs deploy load-dump \
  --image us-central1-docker.pkg.dev/is-rock-alive/cloud-run-images/load-dump:latest \
  --cpu 2 --memory 8Gi --task-timeout 90m \
  --service-account pipeline-sa@is-rock-alive.iam.gserviceaccount.com \
  --region us-central1
gcloud run jobs execute load-dump \
  --update-env-vars ENTITY=event,BQ_PROJECT=is-rock-alive,CHUNK_SIZE_MB=250 \
  --region us-central1

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
- **Cloud Run managed via `gcloud`, not Terraform**: Images are built locally with `docker build` (multi-stage build for minimal image size), pushed to Artifact Registry (`us-central1-docker.pkg.dev/is-rock-alive/cloud-run-images/`), and deployed with `gcloud run jobs deploy --image`. Source-based deployment (`--source`) was attempted but Cloud Build's internal provisioning failed with NOT_FOUND errors despite the API being enabled. The local build approach also gives more control over the image.
- **Artifact Registry managed by Terraform**: A Docker-format repository (`cloud-run-images`) in `us-central1` is provisioned by Terraform (`artifact_registry.tf`). The pipeline SA has `roles/artifactregistry.reader` to pull images at runtime; the user's account pushes images after a one-time `gcloud auth configure-docker us-central1-docker.pkg.dev`.
- **Two ingestion approaches**: Bulk load (`load_dump.py`) is a one-time dump load using `google-cloud-storage` + `google-cloud-bigquery` + `orjson`. Daily incremental uses dlt (pagination, rate limiting, watermarks). dbt owns all transformations.
- **Bulk load skip logic**: Checks if blobs already exist at `gs://landing/mb-dump/{entity}/{dump_date}/`. If files exist, skips the download/upload but still runs the BigQuery load. This makes it safe to rerun after a failed BQ load without re-downloading. To fully rerun, manually delete the GCS files first.
- **Bulk load JSON wrapping**: Each raw JSONL line is wrapped with audit metadata (`json_data`, `_source_file`, `_source_system`, `_batch_id`, `_landing_loaded_at`) before uploading to GCS. The original JSON object is preserved untouched inside `json_data`.
- **Bulk load `_raw_loaded_at` via post-load UPDATE**: BigQuery's `default_value_expression` does not apply during `load_table_from_uri` with `WRITE_TRUNCATE` (table must pre-exist for defaults to apply). Instead, a post-load `UPDATE` sets `_raw_loaded_at = CURRENT_TIMESTAMP()` on all rows.
- **Configurable chunk size**: `CHUNK_SIZE_MB` env var (default 100 MB). Set to 250 MB on Cloud Run for fewer files and faster BQ loads; smaller locally to avoid upload timeouts.
- **Bulk load uses `WRITE_TRUNCATE`**: Full table replace in BigQuery for idempotency.
- **Incremental uses `WRITE_APPEND`**: Raw tables are append-only, dbt staging deduplicates by latest record per MBID.
- **Clustering over partitioning on raw tables**: Partitioning by `_raw_loaded_at` was considered but rejected — the bulk load creates one massive partition while daily incremental loads create tiny ones (well under the 10 GB threshold where BigQuery recommends clustering instead). A large number of small daily partitions would also accumulate toward partition limits over time. Instead, raw tables are clustered by `(_source_system, _raw_loaded_at)`: `_source_system` lets BigQuery skip bulk-load rows when processing only incremental data, and `_raw_loaded_at` enables further pruning by load timestamp within each source system. This optimizes the raw → staging read path for dbt incremental models.
- **GCS landing bucket is a permanent archive**: Data stays in GCS as an immutable copy. If BigQuery loads fail or transformations have bugs, you can reprocess from the landing bucket.
- **dlt stages through GCS**: dlt uses `gs://landing/dlt-staging/` as a staging area before loading into BigQuery. This is why a separate staging bucket is not needed.
- **dbt runs on the Airflow VM**: The e2-small VM (2 vCPUs, 2 GB RAM) handles dbt fine — dbt compiles SQL and sends it to BigQuery, no heavy local processing. This avoids a separate Cloud Run Job for dbt and keeps the architecture simpler.
- **Schema-on-read raw layer**: Raw BigQuery tables use a fixed, entity-agnostic schema: `json_data` (JSON), `_source_file` (STRING), `_source_system` (STRING), `_batch_id` (STRING), `_landing_loaded_at` (TIMESTAMP), `_raw_loaded_at` (TIMESTAMP). No schema autodetect — all parsing and typing happens in dbt staging models via `JSON_VALUE`/`JSON_EXTRACT_ARRAY`. `_row_hash` is computed in dbt staging (not at ingestion) since it serves deduplication, which is a transformation concern. This decouples ingestion from schema management: upstream MusicBrainz schema changes don't break the load job, and all transformation logic lives in one place (dbt).
- **Table naming**: Raw tables are named `{entity}_raw` (e.g., `event_raw`, `release_group_raw`). Hyphens in entity names are converted to underscores.
- **JSONL for raw layer**: Matches source format, BigQuery loads JSONL natively for free.
- **Genre via tags**: MusicBrainz has no genre field — genres come from the tag system. A `genre_mapping` dbt seed maps raw tags to standardized categories.
- **Region**: `us-central1` for all resources (GCS, BigQuery, Cloud Run, GCE). Same-region = free data transfer.

## Data Flow

1. **Bulk ingest (one-time)**: MusicBrainz tar.xz dump → `load_dump.py` on Cloud Run → `gs://landing/mb-dump/{entity}/{dump_date}/` → BigQuery `raw.{entity}_raw` (WRITE_TRUNCATE, fixed schema: `json_data` JSON + audit cols, post-load UPDATE for `_raw_loaded_at`)
2. **Incremental ingest (daily)**: MusicBrainz API → dlt on Cloud Run → `gs://landing/incremental/{entity}/{date}/` → BigQuery `raw` (WRITE_APPEND, same fixed schema)
3. **Transform (dbt on Airflow VM)**:
   - `staging` (views) — extract fields from `json_data` JSON column, cast, rename, deduplicate (latest per MBID), compute `_row_hash`, 1:1 with raw tables
   - `trusted` (tables) — star schema: dims (artists, release_groups, labels, events, genres) + facts + bridges
   - `semantic` (tables) — pre-aggregated for dashboards (rock trends by year/subgenre/label)
4. **Serve**: BigQuery `semantic` → Looker Studio dashboards

## Orchestration

**Daily Airflow DAG** (runs on GCE VM):
1. `CloudRunExecuteJobOperator` → trigger dlt incremental ingest on Cloud Run
2. `BashOperator` → `dbt run` (locally on VM)
3. `BashOperator` → `dbt test` (locally on VM)

**Initial load DAG** (manual, one-time): triggers load_dump.py Cloud Run Job per entity, then full dbt run.

## MusicBrainz API Notes

- Rate limit: 1 request/second — always include a custom User-Agent header
- Entity IDs are MBIDs (UUIDs) — use these as primary keys throughout
- Genres are derived from the tag system, not a dedicated genre field
- A `genre_mapping` dbt seed maps raw tags to standardized genre categories

## User Context

- This is a learning/portfolio project — the user is a GCP/data engineering beginner
- See `ROADMAP.md` for the full phased implementation plan with study references
- **Teaching approach**: Explain concepts, provide references/docs, and describe *how* to do things — but do NOT give ready-made answers (commands, code, configs) upfront. The user wants to learn by figuring it out themselves, not by copying output. Only give direct answers when explicitly asked for them.
