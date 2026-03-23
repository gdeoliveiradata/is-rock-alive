# Is Rock Alive?

An end-to-end data engineering project on GCP that ingests music metadata from [MusicBrainz](https://musicbrainz.org/), builds a lakehouse on GCS + BigQuery, transforms data with dbt, orchestrates pipelines with Airflow, and visualizes trends in Looker Studio — all focused on answering the question: **is rock music still alive?**

## Architecture

![Architecture Diagram](images/Arch%20Diagram.png)

## Tech Stack

| Layer | Technology |
|---|---|
| **Cloud** | GCP (us-central1) |
| **Infrastructure** | Terraform |
| **Storage** | GCS (raw files, permanent archive) + BigQuery (warehouse) |
| **Bulk Ingestion** | Python (`load_dump.py`) on Cloud Run Jobs |
| **Incremental Ingestion** | dlt on Cloud Run Jobs |
| **Transformation** | dbt-core + dbt-bigquery |
| **Orchestration** | Apache Airflow on GCE VM |
| **Visualization** | Looker Studio |
| **CI/CD** | GitHub Actions + Workload Identity Federation |
| **Package Management** | uv |

## Data Model

The project follows a **medallion architecture** (raw → staging → trusted → semantic):

- **Raw** — JSONL loaded as-is into BigQuery with a fixed, entity-agnostic schema: `json_data` (JSON) + audit columns (`_source_file`, `_source_system`, `_batch_id`, `_landing_loaded_at`, `_raw_loaded_at`). No schema autodetect — decouples ingestion from schema changes.
- **Staging** — dbt views that extract fields from `json_data`, type-cast, rename, deduplicate (latest per MBID), and compute `_row_hash`. One view per raw table.
- **Trusted** — dbt tables forming a star schema: dimension tables (artists, release groups, labels, events, genres) and fact/bridge tables.
- **Semantic** — Pre-aggregated dbt tables for Looker Studio dashboards (rock trends by year, subgenre, label).

### Entities

| Entity | Description |
|---|---|
| Artists | Musicians, bands, and other music creators |
| Release Groups | Albums, EPs, singles (groups of releases) |
| Labels | Record labels |
| Events | Concerts, festivals, and other music events |
| Genres | Derived from MusicBrainz's tag system via a genre mapping seed |

## Project Structure

```
├── terraform/              # GCP infrastructure (GCS, BigQuery, IAM)
│   ├── main.tf             # Backend + provider config
│   ├── gcs.tf              # Landing + pipeline buckets
│   ├── bigquery.tf         # raw, staging, trusted, semantic datasets
│   ├── artifact_registry.tf # Docker repo for Cloud Run images
│   ├── iam.tf              # Pipeline SA + 8 role bindings
│   ├── variables.tf        # Input variables
│   └── outputs.tf          # Bucket names, dataset IDs, SA email
├── scripts/
│   ├── load_dump.py        # Bulk ingestion: dump → GCS → BigQuery
│   └── Dockerfile          # Multi-stage build for Cloud Run deployment
├── dbt/                    # Transformation models (staging → trusted → semantic)
│   ├── models/
│   ├── seeds/              # Genre mapping CSV
│   ├── tests/
│   └── macros/
├── dags/                   # Airflow DAGs (daily incremental + dbt)
├── tests/                  # Python unit tests
├── .github/workflows/      # CI/CD pipelines
├── ROADMAP.md              # Phased implementation plan
└── CLAUDE.md               # Project context and design decisions
```

## Key Design Decisions

### Reproducible Infrastructure
Phase 0 is a minimal manual bootstrap (GCP account + Terraform service account). From Phase 1 onward, `terraform apply` provisions everything — GCS buckets, BigQuery datasets, pipeline service account, and all IAM bindings. Anyone cloning the repo can reproduce the full environment.

### Schema-on-Read Raw Layer
Raw tables use a fixed schema (`json_data` JSON + audit columns) regardless of entity type. All parsing and typing happens in dbt staging models via `JSON_VALUE` / `JSON_EXTRACT_ARRAY`. This means upstream MusicBrainz schema changes never break the load job, and all transformation logic lives in one place.

### Two Ingestion Patterns
- **Bulk load** (`load_dump.py`): One-time dump load using `google-cloud-storage` + `google-cloud-bigquery`. Streams tar.xz archives, wraps each JSONL line with audit metadata, chunks into configurable-size files, and loads with `WRITE_TRUNCATE` for idempotency. Includes skip logic — reruns won't re-download if GCS files already exist.
- **Incremental** (dlt): Daily API loads with pagination, rate limiting, and watermarks. Appends to raw tables; dbt staging deduplicates by latest record per MBID.

### ELT, Not ETL
Raw data lands in GCS and BigQuery first, untouched. All transformations happen in BigQuery via dbt — making them version-controlled, testable, and easy to iterate on.

### Least-Privilege IAM
Separate Terraform SA (broad permissions for provisioning) and pipeline SA (scoped to what runtime workloads need). All bindings use additive `google_project_iam_member` to avoid accidentally revoking permissions from other principals.

### Clustering Over Partitioning on Raw Tables
Partitioning by `_raw_loaded_at` was considered but rejected: the bulk load produces one massive partition while daily incremental loads create tiny ones — well under BigQuery's recommended 10 GB per partition threshold. Many small daily partitions would also accumulate toward partition limits over time. Instead, raw tables are clustered by `(_source_system, _raw_loaded_at)`. This lets BigQuery skip bulk-load blocks when dbt staging models process only new incremental data, and further prune by load timestamp within each source system.

### Cost-Conscious Choices
- Single region (`us-central1`) for all resources — free intra-region data transfer
- GCS lifecycle rule transitions landing data to Nearline after 30 days
- Airflow runs on an `e2-small` VM (dbt only compiles SQL; BigQuery does the heavy lifting)
- BigQuery free tier: 1 TB/month queries, 10 GB/month storage

## Getting Started

### Prerequisites

- GCP account with a project and billing enabled
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) (`gcloud`)
- [Terraform](https://developer.hashicorp.com/terraform/install) (v1.5+)
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Python 3.10+

### Setup

```bash
# Clone the repo
git clone https://github.com/<your-username>/is-rock-alive.git
cd is-rock-alive

# Install Python dependencies
uv sync

# Authenticate with GCP
gcloud auth application-default login

# Provision infrastructure
cd terraform
terraform init
terraform plan
terraform apply

# Run bulk ingestion locally for an entity
ENTITY=event uv run python scripts/load_dump.py

# Or deploy and run on Cloud Run Jobs
# One-time: configure Docker auth for Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev

docker build -t us-central1-docker.pkg.dev/<PROJECT_ID>/cloud-run-images/load-dump scripts/
docker push us-central1-docker.pkg.dev/<PROJECT_ID>/cloud-run-images/load-dump

gcloud run jobs deploy load-dump \
  --image us-central1-docker.pkg.dev/<PROJECT_ID>/cloud-run-images/load-dump:latest \
  --cpu 2 \
  --memory 8Gi \
  --task-timeout 90m \
  --service-account pipeline-sa@<PROJECT_ID>.iam.gserviceaccount.com \
  --region us-central1

# Execute per entity
gcloud run jobs execute load-dump \
  --update-env-vars ENTITY=event,BQ_PROJECT=<PROJECT_ID>,CHUNK_SIZE_MB=250 \
  --region us-central1

# Run dbt transformations
cd dbt
dbt run --target dev
dbt test --target dev
```

## Implementation Progress

| Phase | Description | Status |
|---|---|---|
| 0 | Bootstrap (GCP account, Terraform SA) | Done |
| 1 | Infrastructure (Terraform: GCS, BigQuery, IAM) | Done |
| 2 | Bulk Data Ingestion (`load_dump.py`) | Done |
| 3 | dbt Transformation (staging → trusted → semantic) | In progress |
| 4 | Incremental API Loads (dlt) | Planned |
| 5 | Airflow Orchestration (GCE VM) | Planned |
| 6 | Looker Studio Dashboards | Planned |
| 7 | CI/CD (GitHub Actions + Workload Identity Federation) | Planned |
| 8 | Monitoring & Cost Control | Planned |

See [ROADMAP.md](ROADMAP.md) for the detailed phased plan with subtasks and learning resources.

## License

This is a learning/portfolio project. Data sourced from [MusicBrainz](https://musicbrainz.org/) under [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/).
