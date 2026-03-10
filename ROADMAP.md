# MusicBrainz Data Engineering Project - Roadmap

End-to-end data engineering project on GCP: ingest MusicBrainz data (initial bulk load from JSONL dumps + incremental API loads), build a lakehouse on GCS + BigQuery, transform with dbt, orchestrate with Airflow (local Docker for dev, GCE e2-small VM for production), visualize with Looker Studio. Focus: tracking rock artists, albums, labels, events, and genres over the years.

---

## Phase 0: GCP Account & Project Setup ✅

**Why this phase matters**: Every GCP resource lives inside a *project*, which is the unit of billing, permissions, and API access. Getting this right upfront avoids headaches later — a misconfigured project or missing API enablement will block every subsequent phase.

> **Study**: [GCP Resource Hierarchy](https://cloud.google.com/resource-manager/docs/cloud-platform-resource-hierarchy) — understand how organizations, folders, and projects relate. For a personal project you only need a project, but knowing the hierarchy helps you understand IAM inheritance.

### 0.1 Create GCP Account ✅
- [x] Create a Google account (or use existing)
- [x] Go to https://cloud.google.com and sign up for GCP
- [x] Activate the $300 free trial credit (valid 90 days)
- [x] Add a billing account with a payment method

> **Study**: [GCP Free Tier overview](https://cloud.google.com/free/docs/free-cloud-features) — know what's always free (BigQuery 1 TB/mo queries, 10 GB/mo storage) vs. trial credits.

### 0.2 Create GCP Project ✅
- [x] Create a new GCP project (e.g., `musicbrainz-lakehouse`)
- [x] Note the **Project ID** (globally unique, cannot be changed later)
- [x] Link the project to your billing account
- [x] Set budget alerts at $25 and $50 to avoid surprises

> **Why budget alerts?** Cloud costs can spike unexpectedly — a runaway query or forgotten VM can burn through credits fast. Alerts are your safety net.
>
> **Study**: [Creating and managing budgets](https://cloud.google.com/billing/docs/how-to/budgets)

### 0.3 Install Local Tooling ✅
- [x] Install the [Google Cloud SDK (gcloud CLI)](https://cloud.google.com/sdk/docs/install)
- [x] Run `gcloud init` and authenticate with your account
- [x] Set default project: `gcloud config set project <PROJECT_ID>`
- [x] Install Terraform (v1.5+): https://developer.hashicorp.com/terraform/install
- [x] Install dbt-core + dbt-bigquery: `pip install dbt-core dbt-bigquery`
- [x] Install Python 3.10+ (for Airflow DAGs and ingestion scripts)
- [x] Create a GitHub repository for this project

> **Why gcloud CLI?** It's your Swiss Army knife for GCP — authentication, API enablement, debugging, and quick ad-hoc commands. Terraform handles infrastructure, but gcloud fills in the gaps.

### 0.4 Enable Required GCP APIs ✅

**Why enable APIs?** GCP follows a "disabled by default" model. Each service (BigQuery, GCS, IAM, etc.) has an API that must be explicitly turned on before you can use it. This is a security feature — you only expose the surface area you need.

- [x] Enable APIs via gcloud (or Terraform later):
  ```bash
  gcloud services enable \
    bigquery.googleapis.com \
    bigquerystorage.googleapis.com \
    storage.googleapis.com \
    compute.googleapis.com \
    iam.googleapis.com \
    cloudresourcemanager.googleapis.com \
    cloudbuild.googleapis.com \
    secretmanager.googleapis.com \
    serviceusage.googleapis.com \
    run.googleapis.com \
    artifactregistry.googleapis.com
  ```

> **Note**: `run.googleapis.com` and `artifactregistry.googleapis.com` were added after Phase 0 was completed (Cloud Run architecture decision). Enable these two APIs before starting Phase 1.
>
> **Study**: [GCP API enablement](https://cloud.google.com/apis/docs/getting-started#enabling_apis) — what each API controls and why you need it.

### 0.5 Create Service Accounts ✅

**Why service accounts?** In GCP, workloads (scripts, Terraform, Airflow) authenticate as *service accounts*, not as your personal user. This lets you grant fine-grained permissions and follows the principle of least privilege — each component only gets the access it needs, limiting blast radius if credentials are compromised.

- [x] Create a Terraform service account with `roles/editor` + `roles/iam.securityAdmin`
- [x] Create a pipeline service account (used by Airflow/dbt/Cloud Run) with least-privilege roles:
  - `roles/bigquery.dataEditor` — read/write BigQuery tables
  - `roles/bigquery.jobUser` — run BigQuery queries
  - `roles/storage.objectAdmin` — read/write GCS objects
  - `roles/compute.instanceAdmin.v1` — manage the Airflow GCE VM
  - `roles/run.invoker` — trigger Cloud Run jobs (used by Airflow) *(added post Phase 0 — grant before Phase 1)*
  - `roles/run.developer` — deploy/update Cloud Run job definitions *(added post Phase 0 — grant before Phase 1)*
  - `roles/artifactregistry.writer` — push dlt container images *(added post Phase 0 — grant before Phase 1)*
- [x] ~~Download JSON key for Terraform SA~~ — **Skipped.** No JSON keys needed. Locally, Terraform authenticates via Application Default Credentials (`gcloud auth application-default login`). In CI/CD (Phase 7), GitHub Actions will use Workload Identity Federation to impersonate the Terraform SA with short-lived tokens — more secure than long-lived key files. The org policy `constraints/iam.disableServiceAccountKeyCreation` also blocks key creation, which aligns with this approach.
- [ ] ~~Configure Workload Identity Federation for GitHub Actions~~ — **Deferred to Phase 7.** WIF is only needed when GitHub Actions workflows exist. The Terraform SA will be impersonated via WIF at that point.

> **Study**: [IAM overview](https://cloud.google.com/iam/docs/overview) — understand principals, roles, and policies. Then read [Service accounts](https://cloud.google.com/iam/docs/service-account-overview) to understand why workloads use SAs instead of user accounts.
>
> **Study**: [Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation) — how GitHub Actions authenticates to GCP without storing long-lived keys. This is the modern best practice over JSON key files.
>
> **Study**: [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) — how tools like Terraform discover credentials automatically without key files.

---

## Phase 1: Infrastructure with Terraform

**Why Terraform?** Infrastructure as Code (IaC) means your cloud resources are defined in version-controlled files, not clicked together in a console. This gives you reproducibility (tear down and recreate identically), auditability (git history shows who changed what), and collaboration (PR reviews for infra changes). Terraform is the industry standard for multi-cloud IaC.

> **Study**: [Terraform fundamentals](https://developer.hashicorp.com/terraform/tutorials/gcp-get-started) — HashiCorp's official GCP getting-started tutorial. Covers providers, resources, state, plan, and apply.
>
> **Study**: [Terraform state](https://developer.hashicorp.com/terraform/language/state) — why state exists, why it must be stored remotely for team work, and what happens if it gets out of sync.

### 1.1 Terraform Project Structure
```
terraform/
  main.tf              # Provider config, backend
  variables.tf         # Input variables (project_id, region, etc.)
  terraform.tfvars     # Variable values (gitignored)
  gcs.tf               # GCS buckets
  bigquery.tf          # BigQuery datasets
  artifact_registry.tf # Docker repo for dlt container images
  cloud_run.tf         # Cloud Run job for dlt ingestion
  airflow_vm.tf        # GCE VM for Airflow (e2-small, scheduling only)
  iam.tf               # Service accounts and IAM bindings
  outputs.tf           # Output values (bucket names, dataset IDs)
```

> **Why split into multiple files?** Terraform merges all `.tf` files in a directory. Splitting by resource type makes it easier to navigate and review changes. This is a common convention, not a requirement.

### 1.2 Configure Terraform Backend ✅

**Why a remote backend?** Terraform tracks what it has created in a *state file*. By default this is local (`terraform.tfstate`), but storing it in GCS means it's shared, versioned, and not lost if your machine dies. It also enables state locking to prevent concurrent modifications.

- [x] Create a GCS bucket manually for Terraform state: `gs://is-rock-alive-tf-state`
- [x] Configure remote backend in `main.tf`
- [x] Configure the `google` provider with project, region, zone using input variables
- [x] Create `variables.tf` (declarations) and `terraform.tfvars` (values, gitignored)
- [x] Run `terraform init` successfully

> **Lesson learned**: The `backend` block does not support variables, `local`, or any expressions — only literal values. This is because Terraform evaluates the backend *before* processing the rest of the configuration. The bucket name must be hardcoded in `main.tf`.
>
> **Lesson learned**: Don't create the state bucket with Hierarchical Namespace (HNS) enabled — HNS buckets don't support object versioning, which is recommended for state recovery.
>
> **Study**: [GCS backend configuration](https://developer.hashicorp.com/terraform/language/backend/gcs)

### 1.3 Provision GCS Buckets (Data Lake)

**Why GCS as the raw layer?** Cloud object storage (GCS) is the standard landing zone for data lakes: it's cheap ($0.02/GB/mo for Standard), infinitely scalable, supports any file format, and integrates natively with BigQuery for loading. Raw data lives here so you always have an immutable copy of what was ingested — if your transformations have bugs, you can reprocess from raw.

- [ ] **Raw layer bucket**: `gs://<PROJECT_ID>-raw` — landing zone for JSONL dumps and API responses
  - Subdirectories: `musicbrainz-dump/`, `api-incremental/`
  - Lifecycle rule: transition to Nearline after 90 days
- [ ] **Staging bucket**: `gs://<PROJECT_ID>-staging` — temporary processing area
- [ ] **Airflow VM bucket** (optional): `gs://<PROJECT_ID>-airflow` — for syncing DAGs and scripts to the GCE VM

> **Why lifecycle rules?** Old raw data is rarely re-read. Moving it automatically to cheaper storage classes (Nearline: $0.01/GB/mo) saves money without deleting anything.
>
> **Study**: [GCS storage classes](https://cloud.google.com/storage/docs/storage-classes) — Standard vs. Nearline vs. Coldline vs. Archive and when to use each.
>
> **Study**: [Object lifecycle management](https://cloud.google.com/storage/docs/lifecycle)

### 1.4 Provision Artifact Registry

**Why Artifact Registry?** Your dlt ingestion script runs as a Cloud Run job, which requires a container image. Artifact Registry is GCP's managed Docker registry — it stores your container images close to where they run, with IAM-based access control (no separate Docker Hub credentials needed).

- [ ] Create a Docker repository in Artifact Registry (e.g., `dlt-pipelines`)
- [ ] Region: `us-central1` (same as your other resources)

> **Study**: [Artifact Registry overview](https://cloud.google.com/artifact-registry/docs/overview) — how it differs from the older Container Registry, and how to push/pull images.

### 1.5 Provision Cloud Run Job

**Why Cloud Run Jobs?** Your dlt ingestion script is memory-heavy — too much for the e2-small Airflow VM. Cloud Run Jobs let you run batch workloads with up to 32 GB of RAM, and you only pay for the execution time. Airflow stays lightweight (just the scheduler), and Cloud Run handles the heavy lifting.

- [ ] Define a Cloud Run job resource for dlt ingestion (e.g., `musicbrainz-ingest`)
  - Memory: up to 32 GB (tune based on actual dlt needs)
  - CPU: 4-8 vCPUs
  - Timeout: up to 24 hours (adjust based on ingestion duration)
  - Execution SA: pipeline service account
  - Image: from Artifact Registry (`us-central1-docker.pkg.dev/<PROJECT_ID>/dlt-pipelines/musicbrainz-ingest`)
- [ ] Configure secrets via environment variables or Secret Manager (not baked into the image)

> **Note**: The Cloud Run job definition can be created in Terraform now, but the actual container image won't exist until Phase 2 when you build the dlt ingestion script and its Dockerfile.
>
> **Study**: [Cloud Run Jobs overview](https://cloud.google.com/run/docs/create-jobs) — how jobs differ from services, execution environment, and configuration options.

### 1.6 Provision BigQuery Datasets

**Why BigQuery?** It's a serverless, columnar data warehouse that scales to petabytes with zero infrastructure management. You pay per query (first 1 TB/mo free) and per storage (first 10 GB/mo free). For analytics workloads, it's the natural choice on GCP.

**Why multiple datasets?** Datasets in BigQuery are like schemas in PostgreSQL — they're organizational units with independent access controls. Separating raw/staging/curated/analytics lets you grant different permissions (e.g., Looker Studio only reads `analytics`) and makes the data lineage visible.

- [ ] `raw` dataset — external tables or raw loaded data from GCS
- [ ] `staging` dataset — intermediate dbt models (ephemeral/views)
- [ ] `curated` dataset — cleaned, deduplicated, typed tables (dbt models)
- [ ] `analytics` dataset — final star schema / aggregated tables for Looker Studio
- [ ] Set dataset location to `US` (matches GCS region for free data transfer)

> **Why does location matter?** BigQuery charges for cross-region data transfer. If your GCS bucket is in `us-central1` and your BigQuery dataset is in `US` multi-region, the transfer is free. Mixing regions (e.g., EU dataset with US bucket) incurs egress costs.
>
> **Study**: [BigQuery introduction](https://cloud.google.com/bigquery/docs/introduction) — architecture, slots, storage, and pricing model.
>
> **Study**: [Medallion architecture](https://www.databricks.com/glossary/medallion-architecture) — the bronze/silver/gold (raw/curated/analytics) pattern we're using. Originally from Databricks but widely adopted.

### 1.7 Local Airflow with Docker (Development)

**Why start local?** For development and learning, a local Airflow instance in Docker is free and gives you the same DAG authoring experience. Once your DAGs are stable, you'll deploy to a GCE e2-small VM (~$15-30/mo) for production scheduling.

- [ ] Create `docker-compose.yml` for local Airflow (use the [official Airflow Docker Compose](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html))
- [ ] Mount local `dags/` and `scripts/` directories into the container
- [ ] Configure Airflow to use your GCP service account for BigQuery/GCS access
- [ ] Verify the Airflow UI is accessible at `localhost:8080`

> **Study**: [Running Airflow in Docker](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html) — official guide for the Docker Compose setup.
>
> **Study**: [Airflow concepts](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/index.html) — DAGs, tasks, operators, sensors, XComs. Understand these before writing your first DAG.

### 1.8 Provision IAM & Networking
- [ ] Bind pipeline SA roles to BigQuery datasets, GCS buckets, Artifact Registry, and Cloud Run
- [ ] Apply: `terraform init && terraform plan && terraform apply`

> **Study**: [Terraform plan/apply workflow](https://developer.hashicorp.com/terraform/cli/run) — always `plan` before `apply` to see what will change. Treat `plan` output like a code diff.

---

## Phase 2: Data Ingestion - Initial Bulk Load

**Why a bulk load first?** The MusicBrainz database has millions of records spanning decades. Starting from a full dump gives you a complete historical baseline immediately, rather than trying to backfill years of data through the rate-limited API (1 req/sec). The API is then used only for incremental updates going forward.

> **Study**: [MusicBrainz database documentation](https://musicbrainz.org/doc/MusicBrainz_Database) — understand what's in the dump, how often it's published, and the data model.
>
> **Study**: [MusicBrainz schema diagram](https://musicbrainz.org/doc/MusicBrainz_Database/Schema) — the entity relationships. This is critical for understanding how artists, releases, labels, and tags connect.

### 2.1 Download MusicBrainz Data Dump
- [ ] Download the latest MusicBrainz JSON dump from https://musicbrainz.org/doc/MusicBrainz_Database
- [ ] The dump comes as `tar.xz` files containing JSONL
- [ ] Extract locally and inspect the schema for target entities:
  - `artist` — name, type, area, begin/end dates, disambiguation
  - `release_group` — title, type (album/single/EP), artist credit, first release date
  - `label` — name, type, area, begin/end dates
  - `event` — name, type, begin/end dates, place
  - `genre` — name (linked via tags on artists/release_groups)
  - `artist_tag` / `release_group_tag` — genre/tag associations with counts

> **Why JSONL?** JSON Lines (one JSON object per line) is ideal for big data pipelines: it's streamable (no need to parse the whole file), splittable (each line is independent), and directly supported by BigQuery load jobs.

### 2.2 Upload Raw Data to GCS
- [ ] Write a Python script (`scripts/upload_dump.py`) to:
  - Stream-extract the tar.xz (avoid decompressing fully to disk)
  - Upload JSONL files to `gs://<PROJECT_ID>-raw/musicbrainz-dump/<entity>/`
  - Partition large files into manageable chunks (100MB each)
- [ ] Use `google-cloud-storage` Python library or `gsutil -m cp`

> **Why stream-extract?** A 5 GB tar.xz might decompress to 30+ GB. Streaming avoids needing that disk space — you read compressed data and upload directly.
>
> **Why chunk large files?** BigQuery load jobs and GCS uploads perform better with files in the 100MB-1GB range. Too many tiny files = overhead; one huge file = no parallelism.
>
> **Study**: [gsutil cp](https://cloud.google.com/storage/docs/gsutil/commands/cp) — the `-m` flag enables parallel uploads.
>
> **Study**: [google-cloud-storage Python client](https://cloud.google.com/storage/docs/reference/libraries#client-libraries-install-python)

### 2.3 Load into BigQuery Raw Layer

**Why BigQuery load jobs instead of INSERT statements?** Load jobs are BigQuery's bulk ingestion mechanism — they're free (no query cost), handle schema detection, and can ingest gigabytes in minutes. INSERT statements charge per query and are meant for small volumes.

- [ ] Create BigQuery load jobs for each entity:
  - Source: `gs://<PROJECT_ID>-raw/musicbrainz-dump/<entity>/*.jsonl`
  - Destination: `raw.<entity>`
  - Format: JSONL with autodetect schema (review and fix as needed)
  - Write disposition: WRITE_TRUNCATE (full replace for initial load)
- [ ] Write as a Python script (`scripts/initial_load.py`) using `google-cloud-bigquery`
- [ ] Validate row counts against MusicBrainz published statistics

> **Why WRITE_TRUNCATE?** For the initial load, you want a clean slate. TRUNCATE replaces the entire table. For incrementals later, you'll use WRITE_APPEND.
>
> **Why validate row counts?** Data ingestion can silently drop rows (malformed JSON, encoding issues). Comparing your counts to MusicBrainz's published stats catches these problems early.
>
> **Study**: [Loading JSON data into BigQuery](https://cloud.google.com/bigquery/docs/loading-data-cloud-storage-json)
>
> **Study**: [BigQuery Python client](https://cloud.google.com/bigquery/docs/reference/libraries#client-libraries-install-python) — specifically `LoadJobConfig` and `load_table_from_uri`.

---

## Phase 3: Data Ingestion - Incremental API Loads

**Why incremental loads?** MusicBrainz is a living database — new artists debut, albums get released, and metadata gets corrected daily. Incremental loads keep your warehouse current without re-ingesting the entire dump each time. This is the standard ELT pattern: extract changes, load them, then let dbt handle deduplication and merging.

> **Study**: [Change Data Capture patterns](https://www.confluent.io/learn/change-data-capture/) — understand CDC concepts (watermarks, timestamps, event logs). The MusicBrainz API doesn't offer true CDC, so you'll use timestamp-based watermarks.

### 3.1 Understand MusicBrainz API
- [ ] Read API docs: https://musicbrainz.org/doc/MusicBrainz_API
- [ ] Rate limit: 1 request/second (respect this strictly with a custom User-Agent)
- [ ] Register your app and set a descriptive User-Agent header
- [ ] Key endpoints:
  - `GET /ws/2/artist?query=*&fmt=json&offset=N&limit=100`
  - `GET /ws/2/release-group?query=*&fmt=json`
  - Browse endpoints with `inc=` for related data (tags, ratings)

> **Why respect rate limits?** MusicBrainz is a community-run non-profit. Exceeding rate limits gets your IP banned and hurts the service for everyone. Always include a User-Agent with your app name and contact info.
>
> **Study**: [MusicBrainz API rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)
>
> **Study**: [MusicBrainz API search syntax](https://musicbrainz.org/doc/MusicBrainz_API/Search) — Lucene query syntax for filtering entities.

### 3.2 Build Incremental Ingestion Script

**Why watermarks?** A watermark is a bookmark that says "I've ingested everything up to this timestamp." Each run picks up from the last watermark, processes new/updated records, then advances the watermark. This ensures no gaps and no duplicate processing windows (though individual records may still need deduplication).

- [ ] Write `scripts/incremental_ingest.py`:
  - Query the MusicBrainz API for recently updated entities (using `last-updated` or browse with offset)
  - Write responses as JSONL to `gs://<PROJECT_ID>-raw/api-incremental/<entity>/<date>/`
  - Track watermarks (last sync timestamp) in a BigQuery control table or GCS metadata file
  - Handle pagination, retries, and rate limiting
- [ ] Target entities: artists, release_groups, labels, events
- [ ] Schedule: daily incremental pulls

> **Why write to GCS before BigQuery?** This is the "ELT" pattern: raw data always lands in the lake (GCS) first, then gets loaded to the warehouse. If a BigQuery load fails, you don't need to re-fetch from the API — the data is already in GCS.
>
> **Why partition by date?** Storing incrementals as `api-incremental/artist/2026-03-07/data.jsonl` makes it easy to reprocess a specific day, debug issues, and track what was ingested when.

### 3.3 Load Incremental Data to BigQuery
- [ ] Append new records to `raw.<entity>` tables (WRITE_APPEND)
- [ ] Use the `_load_timestamp` column to track when records were ingested
- [ ] Deduplication happens in the dbt staging layer

> **Why append instead of upsert at the raw layer?** Keeping raw as append-only preserves history and makes the ingestion layer simple. If the same artist appears 3 times (from 3 daily loads), all 3 rows are kept in raw. The dbt staging layer then deduplicates by taking the latest record per MBID. This separation of concerns makes debugging much easier.
>
> **Study**: [ELT vs. ETL](https://www.getdbt.com/analytics-engineering/elt-vs-etl) — dbt's explanation of why modern pipelines prefer loading raw data first and transforming inside the warehouse.

---

## Phase 4: Data Transformation with dbt

**Why dbt?** dbt (data build tool) brings software engineering practices to SQL transformations: version control, modularity, testing, documentation, and dependency management. Instead of writing one giant SQL script, you write modular models that dbt compiles and runs in dependency order. It's the industry standard for the "T" in ELT.

> **Study**: [dbt Fundamentals course](https://courses.getdbt.com/courses/fundamentals) — **free official course**, highly recommended. Covers models, tests, documentation, and sources.
>
> **Study**: [dbt best practices](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview) — the official "How we structure our dbt projects" guide. Our staging/curated/analytics layers follow this pattern.
>
> **Study**: [dbt and BigQuery setup](https://docs.getdbt.com/docs/core/connect-data-platform/bigquery-setup)

### 4.1 Initialize dbt Project
- [ ] Run `dbt init musicbrainz` inside the project directory
- [ ] Configure `profiles.yml` for BigQuery connection (service account key or OAuth)
- [ ] Project structure:
  ```
  dbt/
    dbt_project.yml
    profiles.yml          # gitignored, or use env vars
    models/
      staging/            # 1:1 with raw tables, clean + type
      curated/            # business logic, dedup, joins
      analytics/          # final tables for dashboards
    tests/                # custom data tests
    macros/               # reusable SQL macros
    seeds/                # static reference data (genre mappings, etc.)
  ```

> **Why this three-layer structure?**
> - **Staging**: one model per raw table, handles only cleaning (renaming, casting, filtering nulls). No business logic. Materialized as views because they're lightweight wrappers.
> - **Curated**: business logic lives here — deduplication, joins, dimensional modeling. These are your "source of truth" tables.
> - **Analytics**: pre-aggregated tables optimized for specific dashboard queries. Keeps Looker Studio fast by avoiding complex JOINs at query time.

### 4.2 Staging Models (raw -> staging)
- [ ] `stg_artists` — parse JSON, cast types, rename columns, add surrogate keys
- [ ] `stg_release_groups` — normalize release types, extract year from date
- [ ] `stg_labels` — clean label data
- [ ] `stg_events` — parse event dates and types
- [ ] `stg_artist_tags` — flatten tag associations, filter for genre-like tags
- [ ] `stg_release_group_tags` — same for release groups
- [ ] Materialization: `view` (lightweight, always fresh)

> **Why views for staging?** Views don't store data — they're computed on read. Since staging models just rename/cast columns, there's no performance benefit to materializing them as tables. This saves storage cost and ensures staging always reflects the latest raw data.
>
> **Study**: [dbt materializations](https://docs.getdbt.com/docs/build/materializations) — view, table, incremental, and ephemeral. Choosing the right one is a key dbt skill.

### 4.3 Curated Models (staging -> curated)

**Why dimensional modeling?** The star schema (fact tables surrounded by dimension tables) is the gold standard for analytics. Dimension tables describe the "what" (who is the artist, what is the album), while fact tables capture the "events" (an artist released an album in this year with these genres). This structure makes dashboard queries fast and intuitive.

- [ ] `dim_artists` — deduplicated artist dimension with latest record, genre array
- [ ] `dim_release_groups` — albums/EPs/singles with artist and label info
- [ ] `dim_labels` — deduplicated label dimension
- [ ] `dim_genres` — distinct genre list from tags (filtered to music genres)
- [ ] `dim_events` — deduplicated events
- [ ] `fct_artist_releases` — fact table: artist + release_group + date + genre
- [ ] `bridge_artist_genre` — many-to-many: artist <-> genre
- [ ] `bridge_release_group_genre` — many-to-many: release_group <-> genre
- [ ] Materialization: `table` or `incremental` (for large tables)

> **Why bridge tables?** An artist can have multiple genres, and a genre can have multiple artists — that's a many-to-many relationship. Bridge tables resolve this by storing one row per artist-genre pair. Without them, you'd need arrays or repeated JOINs.
>
> **Study**: [Kimball's dimensional modeling](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/) — the foundational methodology. Focus on star schemas, slowly changing dimensions, and fact table design.
>
> **Study**: [dbt incremental models](https://docs.getdbt.com/docs/build/incremental-models) — for large tables, incremental models only process new/changed rows instead of rebuilding the entire table.

### 4.4 Analytics Models (curated -> analytics)
- [ ] `rock_artists_by_year` — count of rock artists with first release per year
- [ ] `rock_albums_by_year` — count of rock release groups per year
- [ ] `rock_albums_by_subgenre_year` — breakdown by rock subgenres over time
- [ ] `top_rock_labels_by_decade` — most prolific rock labels per decade
- [ ] `rock_events_timeline` — rock events over time (festivals, concerts)
- [ ] `genre_evolution` — how genre tag usage changes over time
- [ ] Materialization: `table`

> **Why pre-aggregate?** Looker Studio (and most BI tools) perform best when they query pre-aggregated tables rather than running complex JOINs and GROUP BYs on the fly. These analytics models are the "contract" between your data warehouse and your dashboard.

### 4.5 dbt Tests

**Why test data?** Bad data is silent — a broken JOIN produces zero rows, not an error. dbt tests catch issues like duplicate primary keys, null values in required columns, and broken foreign key relationships. Running tests after every `dbt run` is your quality gate.

- [ ] Add `schema.yml` for every model with:
  - `unique` tests on primary keys
  - `not_null` tests on required columns
  - `accepted_values` for enums (release type, artist type)
  - `relationships` tests for foreign keys between models
- [ ] Custom tests:
  - Row count sanity checks (e.g., artists > 1 million)
  - Date range validation (no future dates beyond current year)
  - Genre tag coverage (% of artists with at least one genre tag)

> **Study**: [dbt testing](https://docs.getdbt.com/docs/build/data-tests) — generic tests, singular tests, and test severity levels.
>
> **Study**: [dbt sources and freshness](https://docs.getdbt.com/docs/build/sources) — declare your raw tables as sources and check that data isn't stale.

### 4.6 dbt Seeds

**Why seeds for genre mapping?** MusicBrainz uses free-form tags, not a controlled genre vocabulary. "hard rock", "Hard Rock", "classic rock", "progressive rock" are all separate tags. A seed CSV lets you define a curated mapping (tag -> parent genre) that lives in version control and can be reviewed/updated like code.

- [ ] `genre_mapping.csv` — mapping of raw MusicBrainz tags to standardized genre categories (e.g., map "hard rock", "classic rock", "alternative rock" -> parent "Rock")
- [ ] `release_type_mapping.csv` — if needed for normalization

> **Study**: [dbt seeds](https://docs.getdbt.com/docs/build/seeds) — when to use seeds vs. source tables. Seeds are for small, static reference data that changes rarely.

---

## Phase 5: Orchestration with Airflow

**Why Airflow?** Data pipelines have dependencies: you can't transform data that hasn't been ingested yet. Airflow lets you define these dependencies as Directed Acyclic Graphs (DAGs), handles scheduling, retries, alerting, and provides a UI to monitor runs. It's the most widely used orchestrator in data engineering.

> **Study**: [Airflow core concepts](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/index.html) — DAGs, tasks, operators, executors, XComs. Read this before writing any DAGs.
>
> **Study**: [Airflow best practices](https://airflow.apache.org/docs/apache-airflow/stable/best-practices.html) — common pitfalls like putting heavy logic in DAG files, misusing XComs, and not setting proper retries.
>
> **Study**: [Astronomer's Airflow guides](https://www.astronomer.io/guides/) — excellent practical tutorials on operators, connections, and patterns.

### 5.1 DAG Structure
```
dags/
  musicbrainz_initial_load.py      # One-time DAG for bulk load
  musicbrainz_daily_incremental.py # Daily: ingest -> load -> transform
  musicbrainz_dbt_run.py           # Can be standalone or part of daily DAG
```

### 5.2 Daily Incremental DAG

**Why this task order?** Each step depends on the previous one completing successfully: you can't load data that hasn't been ingested, and you can't transform data that hasn't been loaded. Airflow enforces this dependency chain — if ingestion fails, it won't attempt the load, preventing cascade failures.

- [ ] Task flow:
  1. `ingest_api` — PythonOperator: run incremental ingest script for each entity
  2. `load_to_bigquery` — BigQueryInsertJobOperator: load new JSONL from GCS to raw
  3. `dbt_run` — BashOperator: `dbt run --profiles-dir /path --project-dir /path`
  4. `dbt_test` — BashOperator: `dbt test --profiles-dir /path --project-dir /path`
  5. `notify_on_failure` — email or Slack alert on failure
- [ ] Schedule: `@daily` (or `0 6 * * *` for 6 AM UTC)
- [ ] Retries: 2, retry delay: 5 minutes

> **Why separate dbt_run and dbt_test?** If tests fail, you want to know about it but you might not want to roll back the models. Separating them lets you see exactly which step failed in the Airflow UI. You could also use `dbt build` which runs both interleaved (test each model right after it's built).

### 5.3 Initial Load DAG
- [ ] One-time trigger (manual) DAG for the bulk dump load
- [ ] Same structure but with WRITE_TRUNCATE and full dbt run

### 5.4 Deploy DAGs (Local Development)
- [ ] Place DAGs in the `dags/` directory mounted to your Docker Airflow
- [ ] Test each task individually with `airflow tasks test <dag_id> <task_id> <date>`
- [ ] Verify full DAG runs in the Airflow UI at `localhost:8080`

### 5.5 Deploy Airflow on GCE VM (Production)

**Why a GCE VM?** Cloud Composer wraps Airflow on GKE and costs ~$300-400/mo minimum — overkill for this project. A single e2-small VM running Airflow with Docker Compose costs ~$15-30/mo if always on. However, for a portfolio project you don't need it running 24/7 — keeping the VM stopped when idle and only starting it for development or pipeline runs brings the cost down to ~$1-2/mo (disk-only charges). This gives you the same real Airflow deployment to showcase, without the always-on bill.

- [ ] Add `airflow_vm.tf` to Terraform:
  - e2-small instance in `us-central1`
  - Attach the pipeline service account
  - Startup script to install Docker and Docker Compose
  - Firewall rule to allow port 8080 (Airflow UI) from your IP only
- [ ] Create a deployment script to sync DAGs and scripts to the VM (e.g., `gcloud compute scp` or GCS bucket sync)
- [ ] SSH into the VM and run Airflow via Docker Compose (same `docker-compose.yml` as local dev)
- [ ] Configure Airflow connections to use the VM's attached service account for GCP auth
- [ ] Verify the Airflow UI is accessible at `http://<VM_EXTERNAL_IP>:8080`
- [ ] Set up a basic monitoring alert (VM uptime check) in GCP
- [ ] Configure VM cost optimization (pick one or both):
  - **Manual start/stop**: use `gcloud compute instances start/stop` when developing or demoing
  - **GCE instance schedule**: auto-start/stop the VM during specific hours (e.g., 6-8 AM UTC for daily pipeline runs) — reduces cost from ~$15-30/mo to ~$1-2/mo

> **Study**: [GCE instance creation with Terraform](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_instance) — Terraform resource for managing GCE VMs.
>
> **Study**: [GCE instance schedules](https://cloud.google.com/compute/docs/instances/schedule-instance-start-stop) — how to auto-start/stop VMs on a schedule to save costs.
>
> **Security note**: Restrict Airflow UI access via firewall rules (allow only your IP). For extra security, use IAP (Identity-Aware Proxy) to tunnel SSH and web access without exposing ports publicly.

---

## Phase 6: Dashboards with Looker Studio

**Why Looker Studio?** It's free, natively integrates with BigQuery (no connectors needed), and is good enough for most analytics dashboards. For a learning project, it lets you focus on the data platform rather than self-hosting a BI tool.

> **Study**: [Looker Studio tutorial](https://support.google.com/looker-studio/answer/9171315) — official getting started guide.
>
> **Study**: [Connecting BigQuery to Looker Studio](https://support.google.com/looker-studio/answer/6370296)
>
> **Study**: [Dashboard design principles](https://www.storytellingwithdata.com/) — "Storytelling with Data" by Cole Nussbaumer Knaflic. The book is worth reading; the blog has free content on effective data visualization.

### 6.1 Connect Looker Studio to BigQuery
- [ ] Go to https://lookerstudio.google.com
- [ ] Create a new data source -> BigQuery -> select `analytics` dataset
- [ ] Add each analytics table as a data source

### 6.2 Build Dashboards
- [ ] **Rock Music Over the Years** dashboard:
  - Line chart: number of rock artists by year (debut year)
  - Line chart: number of rock albums released per year
  - Stacked area chart: rock subgenres over time
  - Bar chart: top rock labels by decade (with decade filter)
  - Timeline / scatter: major rock events
  - Scorecard KPIs: total rock artists, total rock albums, peak year
- [ ] Add interactive filters: date range, subgenre, country/area
- [ ] Style and publish the dashboard

---

## Phase 7: CI/CD with GitHub Actions

**Why CI/CD?** Continuous Integration / Continuous Deployment automates testing and deployment. When you push code, CI runs linting and tests; when you merge to main, CD deploys changes. This catches bugs before they reach production and eliminates manual deployment steps.

> **Study**: [GitHub Actions quickstart](https://docs.github.com/en/actions/quickstart) — understand workflows, jobs, steps, and triggers.
>
> **Study**: [Terraform CI/CD with GitHub Actions](https://developer.hashicorp.com/terraform/tutorials/automation/github-actions) — official HashiCorp tutorial.
>
> **Study**: [dbt CI/CD](https://docs.getdbt.com/docs/deploy/continuous-integration) — how to run dbt in CI against a dev/PR-specific dataset.

### 7.1 Repository Structure
```
.github/
  workflows/
    terraform.yml        # Plan on PR, apply on merge to main
    dbt.yml              # dbt build + test on PR (against a dev dataset)
    lint.yml             # Python linting, SQL linting (sqlfluff)
terraform/
dbt/
dags/
scripts/
tests/
CLAUDE.md
README.md
```

### 7.2 Terraform CI/CD

**Why plan on PR, apply on merge?** Running `terraform plan` on a PR lets reviewers see exactly what infrastructure will change before approving. Applying only on merge to main ensures only reviewed changes reach production. This is the standard GitOps workflow for IaC.

- [ ] On PR: `terraform fmt -check`, `terraform validate`, `terraform plan`
- [ ] On merge to main: `terraform apply -auto-approve`
- [ ] Configure Workload Identity Federation for keyless GCP auth from GitHub Actions (deferred from Phase 0.5 — set up the trust relationship between GCP and GitHub, so workflows can impersonate the Terraform SA)
- [ ] Store project config in GitHub Secrets / Variables

### 7.3 dbt CI/CD
- [ ] On PR: `dbt build --target dev` (runs models + tests against a dev dataset)
- [ ] On merge to main: optionally trigger a production dbt run
- [ ] Lint SQL with `sqlfluff` (configure for BigQuery dialect)

> **Study**: [sqlfluff](https://docs.sqlfluff.com/en/stable/) — SQL linter and formatter. Configure it for BigQuery dialect to catch syntax issues before they hit production.

### 7.4 Python CI/CD
- [ ] Lint with `ruff` or `flake8`
- [ ] Type check with `mypy` (optional)
- [ ] Unit tests with `pytest` for ingestion scripts

---

## Phase 8: Monitoring, Cost Control & Hardening

**Why monitoring?** Pipelines fail silently — an API endpoint changes, a schema drifts, a BigQuery job times out. Without monitoring, you might not notice for days that your dashboard is showing stale data. Monitoring closes this loop.

> **Study**: [GCP Cloud Monitoring](https://cloud.google.com/monitoring/docs/monitoring-overview) — metrics, alerts, and dashboards for GCP services.
>
> **Study**: [BigQuery admin reference guide](https://cloud.google.com/bigquery/docs/best-practices-costs) — cost optimization, slot management, and query performance.

### 8.1 Cost Management
- [ ] Set up billing budget alerts at $25, $50, $75
- [ ] Use BigQuery on-demand pricing (first 1 TB/mo queries free)
- [ ] Set BigQuery per-user query quotas to prevent runaway costs
- [ ] Use GCS lifecycle rules to move old raw data to Nearline/Coldline
- [ ] Review the [GCP Pricing Calculator](https://cloud.google.com/products/calculator) to estimate monthly costs

### 8.2 Monitoring
- [ ] Set up Airflow email alerts on DAG failures
- [ ] Create a dbt freshness check (`dbt source freshness`) in the daily DAG
- [ ] Monitor BigQuery slot usage and query costs in the console

### 8.3 Security
- [ ] Never commit service account keys to git (use `.gitignore`)
- [ ] Use Secret Manager for any API keys or credentials
- [ ] Principle of least privilege on all service accounts
- [ ] Enable audit logging on the GCP project

> **Study**: [GCP security best practices](https://cloud.google.com/docs/enterprise/best-practices-for-enterprise-organizations#securing-your-environment) — overview of securing a GCP environment.

---

## Execution Order Summary

| Order | Phase | Estimated Effort | Depends On |
|-------|-------|-----------------|------------|
| 1 | Phase 0: GCP Account & Tooling | 1-2 hours | Nothing |
| 2 | Phase 1: Terraform Infrastructure | 4-8 hours | Phase 0 |
| 3 | Phase 2: Bulk Data Ingestion | 4-6 hours | Phase 1 |
| 4 | Phase 4.1-4.2: dbt Setup + Staging | 4-6 hours | Phase 2 |
| 5 | Phase 4.3-4.6: dbt Curated + Analytics | 6-10 hours | Phase 4.2 |
| 6 | Phase 3: Incremental Ingestion | 4-6 hours | Phase 2 |
| 7 | Phase 5: Airflow DAGs | 4-8 hours | Phase 3, 4 |
| 8 | Phase 6: Looker Studio Dashboards | 3-5 hours | Phase 4.4 |
| 9 | Phase 7: CI/CD | 3-5 hours | Phase 1, 4 |
| 10 | Phase 8: Monitoring & Hardening | 2-4 hours | All above |

---

## Recommended Learning Path

Before diving into implementation, consider studying these topics in order. You don't need to finish everything before starting — but having the mental model helps you understand *why* you're doing each step.

### Foundations (read/watch before Phase 0)
1. [GCP Resource Hierarchy](https://cloud.google.com/resource-manager/docs/cloud-platform-resource-hierarchy) — projects, IAM, billing
2. [GCP IAM overview](https://cloud.google.com/iam/docs/overview) — how permissions work
3. [Terraform GCP tutorial](https://developer.hashicorp.com/terraform/tutorials/gcp-get-started) — hands-on, ~2 hours

### Data Engineering Concepts (read before Phase 2)
4. [Medallion architecture (raw/curated/analytics)](https://www.databricks.com/glossary/medallion-architecture) — the layered data pattern
5. [ELT vs. ETL](https://www.getdbt.com/analytics-engineering/elt-vs-etl) — why we load first, transform second
6. [Kimball dimensional modeling](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/) — star schemas, facts, and dimensions

### Tool-Specific (read when you reach the relevant phase)
7. [dbt Fundamentals free course](https://courses.getdbt.com/courses/fundamentals) — 4-5 hours, covers everything you need
8. [Airflow core concepts](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/index.html) — DAGs, operators, scheduling
9. [BigQuery best practices](https://cloud.google.com/bigquery/docs/best-practices-performance-overview) — partitioning, clustering, query optimization

### Books (optional deep dives)
10. *Fundamentals of Data Engineering* by Joe Reis & Matt Housley — the most comprehensive modern DE book, covers the full lifecycle
11. *The Data Warehouse Toolkit* by Ralph Kimball — the bible for dimensional modeling
12. *Storytelling with Data* by Cole Nussbaumer Knaflic — for making your dashboards actually useful

---

## Key Decisions & Notes

- **Region**: `us-central1` — cheapest for most GCP services, free BigQuery data transfer within US multi-region.
- **Local Airflow for dev, GCE VM for prod**: Develop and test DAGs locally with Docker Compose. Deploy to a GCE e2-small VM (~$15-30/mo) for production scheduling — much cheaper than Cloud Composer (~$300-400/mo).
- **Ephemeral compute for ingestion**: dlt ingestion runs on Cloud Run Jobs (up to 32 GB RAM, pay-per-use), not on the Airflow VM. Airflow only orchestrates — it triggers Cloud Run jobs and monitors their status. This keeps the Airflow VM small (e2-small) while allowing memory-heavy ingestion workloads. Container images are stored in Artifact Registry.
- **MusicBrainz API rate limit**: 1 req/sec. For large incremental catches, consider using the database dumps instead of the API.
- **Genre identification**: MusicBrainz uses a tag system, not a strict genre hierarchy. You'll need a `genre_mapping` seed to categorize tags like "hard rock", "punk rock", "progressive rock" under "Rock".
- **Incremental strategy**: Use `_load_timestamp` watermarks + dbt incremental models with deduplication on MusicBrainz entity IDs (MBIDs).
