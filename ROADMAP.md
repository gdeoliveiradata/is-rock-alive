# MusicBrainz Data Engineering Project - Roadmap

End-to-end data engineering project on GCP: ingest MusicBrainz data (initial bulk load from JSONL dumps + daily incremental via API), build a lakehouse on GCS + BigQuery, transform with dbt, orchestrate with Airflow, visualize with Looker Studio. Focus: tracking rock artists, albums, labels, events, and genres over the years.

**Design principle — reproducibility**: The entire project should be reproducible by anyone who clones the repo. Phase 0 is a minimal manual bootstrap (GCP account + Terraform SA). From Phase 1 onward, `terraform apply` provisions all infrastructure, service accounts, IAM bindings, and Artifact Registry. Cloud Run Jobs are the exception — they're managed via `gcloud` (images built locally with Docker, pushed to Artifact Registry, deployed with `gcloud run jobs deploy --image`).

---

## Phase 0: Bootstrap

**Why this phase matters**: Every GCP resource lives inside a *project*, which is the unit of billing, permissions, and API access. This phase is the minimal manual setup that can't be automated — creating the GCP project and the Terraform service account (chicken-and-egg: Terraform can't create the SA it needs to authenticate as).

> **Study**: [GCP Resource Hierarchy](https://cloud.google.com/resource-manager/docs/cloud-platform-resource-hierarchy) — understand how organizations, folders, and projects relate. For a personal project you only need a project, but knowing the hierarchy helps you understand IAM inheritance.

### 0.1 Create GCP Account & Project
- [x] Create a Google account (or use existing)
- [x] Sign up for GCP at https://cloud.google.com and activate the $300 free trial
- [x] Create a new GCP project (e.g., `musicbrainz-lakehouse`)
- [x] Link the project to a billing account
- [x] Set budget alerts at $25 and $50

> **Why budget alerts?** Cloud costs can spike unexpectedly — a runaway query or forgotten VM can burn through credits fast. Alerts are your safety net.
>
> **Study**: [GCP Free Tier overview](https://cloud.google.com/free/docs/free-cloud-features) — know what's always free (BigQuery 1 TB/mo queries, 10 GB/mo storage) vs. trial credits.
>
> **Study**: [Creating and managing budgets](https://cloud.google.com/billing/docs/how-to/budgets)

### 0.2 Install Local Tooling
- [x] Install the [Google Cloud SDK (gcloud CLI)](https://cloud.google.com/sdk/docs/install)
- [x] Run `gcloud init` and authenticate with your account
- [x] Set default project: `gcloud config set project <PROJECT_ID>`
- [x] Install Terraform (v1.5+): https://developer.hashicorp.com/terraform/install
- [x] Install dbt-core + dbt-bigquery: `pip install dbt-core dbt-bigquery`
- [x] Install Python 3.10+
- [x] Create a GitHub repository for this project

### 0.3 Enable Required GCP APIs

**Why enable APIs?** GCP follows a "disabled by default" model. Each service has an API that must be explicitly turned on before Terraform or any other tool can manage resources for it.

- [x] Enable APIs via gcloud:
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
    run.googleapis.com
  ```

> **Study**: [GCP API enablement](https://cloud.google.com/apis/docs/getting-started#enabling_apis) — what each API controls and why you need it.

### 0.4 Create Terraform Service Account (manual bootstrap)

**Why manual?** This is the chicken-and-egg of IaC: Terraform needs a service account to authenticate, so this SA must exist before Terraform runs. Everything else — including the pipeline SA and all IAM bindings — will be managed by Terraform in Phase 1.

- [x] Create the Terraform SA:
  ```bash
  gcloud iam service-accounts create terraform-sa \
    --display-name="Terraform Service Account"
  ```
- [x] Grant it the permissions it needs to manage the project:
  - `roles/editor` — create/manage most GCP resources
  - `roles/iam.securityAdmin` — manage IAM bindings for other service accounts
- [x] Set up Application Default Credentials for local development:
  ```bash
  gcloud auth application-default login
  ```

> **Why these roles?** `roles/editor` lets Terraform create GCS buckets, BigQuery datasets, GCE VMs, etc. `roles/iam.securityAdmin` lets Terraform assign roles to the pipeline SA. Together they cover everything Terraform needs to manage in this project.
>
> **Why no JSON key files?** Application Default Credentials (ADC) let Terraform authenticate using your local `gcloud` login — no key files to manage, rotate, or accidentally commit. In CI/CD (Phase 7), GitHub Actions will use Workload Identity Federation for the same keyless approach.
>
> **Study**: [IAM overview](https://cloud.google.com/iam/docs/overview) — understand principals, roles, and policies.
>
> **Study**: [Service accounts](https://cloud.google.com/iam/docs/service-account-overview) — why workloads use SAs instead of user accounts.
>
> **Study**: [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) — how tools discover credentials automatically.

---

## Phase 1: Infrastructure with Terraform

**Why Terraform?** Infrastructure as Code (IaC) means your cloud resources are defined in version-controlled files, not clicked together in a console. This gives you reproducibility (tear down and recreate identically), auditability (git history shows who changed what), and collaboration (PR reviews for infra changes). Terraform is the industry standard for multi-cloud IaC.

> **Study**: [Terraform fundamentals](https://developer.hashicorp.com/terraform/tutorials/gcp-get-started) — HashiCorp's official GCP getting-started tutorial. Covers providers, resources, state, plan, and apply.
>
> **Study**: [Terraform state](https://developer.hashicorp.com/terraform/language/state) — why state exists, why it must be stored remotely for team work, and what happens if it gets out of sync.
>
> **Study**: [Terraform resources](https://developer.hashicorp.com/terraform/language/resources) — syntax and behavior of resource blocks, including lifecycle, meta-arguments, and dependencies.

### 1.1 Terraform Project Structure
```
terraform/
  main.tf              # Provider config, backend
  variables.tf         # Input variables (project_id, region, etc.)
  terraform.tfvars     # Variable values (gitignored)
  gcs.tf               # GCS buckets
  bigquery.tf          # BigQuery datasets
  iam.tf               # Pipeline service account and IAM bindings
  artifact_registry.tf # Docker repo for Cloud Run container images
  airflow_vm.tf        # GCE VM for Airflow (added in Phase 5)
  outputs.tf           # Output values (bucket names, dataset IDs, SA emails)
```

> **Why split into multiple files?** Terraform merges all `.tf` files in a directory. Splitting by resource type makes it easier to navigate and review changes. This is a common convention, not a requirement.

### 1.2 Configure Terraform Backend

**Why a remote backend?** Terraform tracks what it has created in a *state file*. By default this is local (`terraform.tfstate`), but storing it in GCS means it's shared, versioned, and not lost if your machine dies. It also enables state locking to prevent concurrent modifications.

- [x] Create a GCS bucket manually for Terraform state: `gs://<PROJECT_ID>-tf-state`
- [x] Configure remote backend in `main.tf`
- [x] Configure the `google` provider with project, region, zone using input variables
- [x] Create `variables.tf` (declarations) and `terraform.tfvars` (values, gitignored)
- [x] Run `terraform init` successfully

> **Important**: The `backend` block does not support variables or expressions — only literal values. This is because Terraform evaluates the backend *before* processing the rest of the configuration. The bucket name must be hardcoded in `main.tf`.
>
> **Study**: [GCS backend configuration](https://developer.hashicorp.com/terraform/language/backend/gcs)

### 1.3 Provision GCS Buckets (Data Lake)

**Why GCS as the raw layer?** Cloud object storage is the standard landing zone for data lakes: it's cheap ($0.02/GB/mo for Standard), infinitely scalable, supports any file format, and integrates natively with BigQuery for loading. Raw data lives here so you always have an immutable copy of what was ingested — if your transformations have bugs, you can reprocess from raw.

- [x] **Landing bucket**: `gs://<PROJECT_ID>-landing` — permanent archive of all ingested data (bulk + incremental + dlt staging)
  - Lifecycle rule: transition to Nearline after 30 days
  - Path structure: `bulk/{entity}/`, `incremental/{entity}/{date}/`, `dlt-staging/`
- [x] ~~**Staging bucket**: `gs://<PROJECT_ID>-staging`~~ — removed (2026-03-16): no pipeline used it. dlt stages through `gs://landing/dlt-staging/` instead.
- [x] **Pipeline bucket**: `gs://<PROJECT_ID>-pipeline` — for syncing DAGs and scripts to the GCE VM
- [x] All buckets use `uniform_bucket_level_access = true` (IAM-only, no legacy ACLs)

> **Why lifecycle rules?** Old raw data is rarely re-read. Moving it automatically to cheaper storage classes (Nearline: $0.01/GB/mo) saves money without deleting anything.
>
> **Study**: [GCS storage classes](https://cloud.google.com/storage/docs/storage-classes) — Standard vs. Nearline vs. Coldline vs. Archive and when to use each.
>
> **Study**: [Object lifecycle management](https://cloud.google.com/storage/docs/lifecycle)
>
> **Study**: [Terraform for Cloud Storage](https://docs.cloud.google.com/storage/docs/terraform-for-cloud-storage)

### 1.4 Provision BigQuery Datasets

**Why BigQuery?** It's a serverless, columnar data warehouse that scales to petabytes with zero infrastructure management. You pay per query (first 1 TB/mo free) and per storage (first 10 GB/mo free). For analytics workloads, it's the natural choice on GCP.

**Why multiple datasets?** Datasets in BigQuery are like schemas in PostgreSQL — they're organizational units with independent access controls. Separating raw/staging/trusted/semantic lets you grant different permissions (e.g., Looker Studio only reads `semantic`) and makes the data lineage visible.

- [x] `raw` dataset — loaded data from GCS JSONL files
- [x] `staging` dataset — intermediate dbt models (views)
- [x] `trusted` dataset — cleaned, deduplicated, typed tables (dbt models)
- [x] `semantic` dataset — final aggregated tables for Looker Studio
- [x] Set dataset location to `us-central1` (same region as GCS buckets, free data transfer)

> **Why does location matter?** BigQuery charges for cross-region data transfer. If your GCS bucket is in `us-central1` and your BigQuery dataset is in `US` multi-region, the transfer is free. Mixing regions (e.g., EU dataset with US bucket) incurs egress costs.
>
> **Study**: [BigQuery introduction](https://cloud.google.com/bigquery/docs/introduction) — architecture, slots, storage, and pricing model.
>
> **Study**: [Medallion architecture](https://www.databricks.com/glossary/medallion-architecture) — the bronze/silver/gold (raw/trusted/semantic) pattern. Originally from Databricks but widely adopted.

### 1.5 IAM: Pipeline Service Account & Role Bindings

**Why manage IAM in Terraform?** Service accounts and their role bindings are infrastructure. Managing them in Terraform means anyone who clones the repo gets the complete picture — not just the buckets and datasets, but also *who* can access them and with what permissions. It also makes IAM changes auditable through git history.

**Why a separate pipeline SA?** The pipeline SA is used by Airflow, dbt, Cloud Run Jobs, and any runtime workload. It gets only the permissions these workloads need — not the broad `roles/editor` that the Terraform SA has. This follows the principle of least privilege.

- [x] Create the pipeline service account (`pipeline-sa`) via Terraform
- [x] Bind the following roles to the pipeline SA using additive IAM resources:
  - `roles/bigquery.dataEditor` — read/write BigQuery tables
  - `roles/bigquery.jobUser` — run BigQuery queries
  - `roles/storage.objectAdmin` — read/write GCS objects
  - `roles/compute.instanceAdmin.v1` — manage the Airflow GCE VM
  - `roles/run.invoker` — trigger Cloud Run jobs (used by Airflow)
  - `roles/serviceusage.serviceUsageConsumer` — required for API access
  - `roles/iam.serviceAccountUser` — attach SAs to Cloud Run jobs
  - `roles/artifactregistry.reader` — pull built container images from Artifact Registry

> **Critical concept — IAM binding types in Terraform**: Terraform offers three IAM resources for GCP. Picking the wrong one can lock you out of your project or strip permissions from other principals:
>
> - `google_project_iam_policy` — **fully authoritative**: replaces ALL bindings for ALL roles in the project. Use this and you'll wipe out your own user permissions and any Google-managed SAs.
> - `google_project_iam_binding` — **authoritative per role**: replaces all members for a specific role. Dangerous if other principals (like your user account) also hold that role.
> - `google_project_iam_member` — **additive**: adds one member to one role without touching anything else. This is the safest option for a project where your personal user account and Google-managed SAs also need to retain access.
>
> **Study**: [Terraform google_project_iam docs](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/google_project_iam) — read the warnings at the top carefully.
>
> **Study**: [Terraform google_service_account](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/google_service_account)

### 1.6 Outputs

- [x] Create `outputs.tf` with useful values: bucket names, dataset IDs, pipeline SA email
- [x] These outputs can be referenced by scripts and CI/CD pipelines

> **Study**: [Terraform outputs](https://developer.hashicorp.com/terraform/language/values/outputs)

### 1.7 Apply and Verify

- [x] Run `terraform plan` — review every resource that will be created
- [x] Run `terraform apply` — provision all resources
- [x] Verify in the GCP Console: buckets, datasets, SA, and role bindings exist

> **Study**: [Terraform plan/apply workflow](https://developer.hashicorp.com/terraform/cli/run) — always `plan` before `apply` to see what will change. Treat `plan` output like a code diff.

---

## Phase 2: Data Ingestion — Initial Bulk Load

One Python script (`scripts/load_dump.py`) that downloads a MusicBrainz entity dump, chunks it into JSONL files, uploads to GCS, and loads into BigQuery. Runs locally first, then on Cloud Run Jobs.

**Target script pipeline:**
```
Download (HTTP → temp file) → Extract (tar.xz from disk) → Chunk (JSONL by ~100 MB) → Upload (GCS) → Load (BigQuery) → Validate row counts
```

**Key design decisions:**
- **One script, per-entity executions** — reads `ENTITY` env var, derives all paths. One Cloud Run Job, executed per entity with `--update-env-vars`.
- **Download-first** — saves tar.xz to a temp file before extracting. Decouples HTTP download from GCS uploads, preventing connection drops.
- **Byte-based chunking** — splits JSONL at configurable boundaries (`CHUNK_SIZE_MB` env var, default 100 MB). Byte tracking uses the wrapped line size for accurate chunking.
- **JSON wrapping** — each raw JSONL line is parsed and nested under `json_data`, with audit metadata (`_source_file`, `_source_system`, `_batch_id`, `_landing_loaded_at`) added before upload. Original JSON is preserved untouched. Uses `orjson` for faster parse/serialize.
- **Skip logic gates upload only** — checks if blobs exist at `gs://landing/mb-dump/{entity}/{dump_date}/`. If files exist, skips download/upload but still runs the BigQuery load. Safe to rerun after a failed BQ load. To fully rerun, delete the GCS files first.
- **`WRITE_TRUNCATE`** — full table replace for idempotency. Re-running replaces everything.
- **Post-load UPDATE for `_raw_loaded_at`** — BigQuery's `default_value_expression` does not apply during `load_table_from_uri` with `WRITE_TRUNCATE`. A post-load `UPDATE` sets `_raw_loaded_at = CURRENT_TIMESTAMP()` on all rows.
- **`_row_hash` computed in dbt** — hash serves deduplication (a transformation concern), so it's computed in dbt staging via `SHA256(TO_JSON_STRING(json_data))`, not at ingestion.
- **GCS paths** — bulk load writes to `gs://landing/mb-dump/{entity}/{dump_date}/`, separate from incremental at `gs://landing/incremental/{entity}/{date}/`.
- **Table naming** — raw tables are named `{entity}_raw` (e.g., `event_raw`, `release_group_raw`). Hyphens converted to underscores.
- **`logging` module** — structured output for Cloud Run's Cloud Logging.

> **Study**: [MusicBrainz database docs](https://musicbrainz.org/doc/MusicBrainz_Database) | [Schema diagram](https://musicbrainz.org/doc/MusicBrainz_Database/Schema)

### 2.1 Explore the Source Data

Before writing any code, understand what you're ingesting.

- [x] Browse the dump index at https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/
- [x] Note the entities and sizes: `event` (~42 MB), `label` (~161 MB), `release-group` (~1 GB), `artist` (~2 GB)
- [x] Download `event.tar.xz` locally and inspect the structure: it's a tar containing `mbdump/event`, a JSONL file (one JSON object per line)
- [x] Inspect a few lines — note the nested fields (relations, tags, aliases, area, life-span)
- [x] Notice that the dump index has a `LATEST` file with the latest dump date string

> **Study**: [Python `tarfile`](https://docs.python.org/3/library/tarfile.html) — `tarfile.open()` with mode `r:xz`, iterating members, `extractfile()`.
>
> **Study**: [JSON Lines format](https://jsonlines.org/)

### 2.2 Understand BigQuery JSON Loading

How BigQuery loads JSONL drives your chunking and schema decisions.

**Raw table schema approach — schema-on-read with a JSON column**: Instead of using BigQuery's schema autodetect to create typed columns directly from JSONL, the raw layer uses a fixed, entity-agnostic schema: a handful of audit columns plus a single `data` column (BigQuery `JSON` type) that stores the entire JSON line as-is. All parsing and typing happens in the dbt staging layer (Phase 3).

This decouples ingestion from schema management — upstream schema changes in MusicBrainz won't break the load job, and all transformation logic lives in one place (dbt).

**Raw table schema:**
| Column | Type | Mode | Description |
|--------|------|------|-------------|
| `json_data` | `JSON` | REQUIRED | The full JSON object from one JSONL line, wrapped at ingestion time |
| `_source_file` | `STRING` | REQUIRED | GCS blob path the row came from (traceability back to the exact file) |
| `_source_system` | `STRING` | REQUIRED | Which pipeline produced the row (e.g., `MusicBrainz JSON Dump`, `incremental_api`) |
| `_batch_id` | `STRING` | REQUIRED | Identifier per load run (dump date for bulk, execution ID for incremental) |
| `_landing_loaded_at` | `TIMESTAMP` | REQUIRED | When the row was uploaded to GCS (one value per batch) |
| `_raw_loaded_at` | `TIMESTAMP` | NULLABLE | When the row was loaded into BigQuery (set via post-load UPDATE) |

**Note:** `_row_hash` is not in the raw schema — it's computed in dbt staging via `SHA256(TO_JSON_STRING(json_data))` since it serves deduplication, a transformation concern.

- [x] What's the BigQuery `JSON` data type? How does it differ from storing JSON as `STRING`?
- [x] How do you define an explicit schema in `LoadJobConfig` instead of using `autodetect`?
- [x] What's `source_format` for JSONL? (`NEWLINE_DELIMITED_JSON`)
- [x] What are the load job limits? (max file size, row size, nested depth)
- [x] `WRITE_TRUNCATE` vs. `WRITE_APPEND` — which makes the bulk load idempotent?
- [x] What's a wildcard URI? (`gs://bucket/entity/*.jsonl` loads all chunks in one job)
- [x] How do you query a `JSON` column? (`JSON_VALUE()`, `JSON_EXTRACT()`, `JSON_EXTRACT_ARRAY()`)

> **Study**: [Loading JSON into BigQuery](https://cloud.google.com/bigquery/docs/loading-data-cloud-storage-json) | [Schema autodetection](https://cloud.google.com/bigquery/docs/schema-detect) | [Load job limits](https://cloud.google.com/bigquery/quotas#load_jobs)
>
> **Study**: [BigQuery Python client — `LoadJobConfig`](https://cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.job.LoadJobConfig)
>
> **Study**: [BigQuery JSON data type](https://cloud.google.com/bigquery/docs/reference/standard-sql/json-types) — native JSON type, querying with `JSON_VALUE` and `JSON_QUERY`, and performance considerations vs. `STRING`.
>
> **Study**: [Querying JSON data in BigQuery](https://cloud.google.com/bigquery/docs/json-data) — extracting fields, arrays, and nested objects from JSON columns.

**Clustering over partitioning on raw tables**: Partitioning by `_raw_loaded_at` was the initial approach, but analysis showed it was a poor fit. The bulk load creates one massive partition (all rows share the same timestamp), while daily incremental loads create tiny partitions — well under BigQuery's recommended 10 GB per partition threshold. Many small daily partitions would also accumulate toward the 4,000-partition limit over time. Per [BigQuery's own guidance](https://cloud.google.com/bigquery/docs/partitioned-tables#when_to_use_partitioning), clustering is preferred when partitions would be small or numerous.

Raw tables are instead clustered by `(_source_system, _raw_loaded_at)`:
- `_source_system` lets BigQuery skip bulk-load blocks when dbt staging models process only new incremental data (e.g., filtering for `_source_system = 'incremental_api'`)
- `_raw_loaded_at` enables further block pruning by load timestamp within each source system, optimizing dbt incremental model runs that only need rows since the last execution

> **Study**: [Partitioned tables — when to use partitioning](https://cloud.google.com/bigquery/docs/partitioned-tables#when_to_use_partitioning) — the "Consider clustering" bullet points explain when clustering is the better choice.
>
> **Study**: [Introduction to clustered tables](https://cloud.google.com/bigquery/docs/clustered-tables) — how clustering works, column order, and automatic re-clustering.

### 2.3 Write the Script — Step by Step

Build `scripts/load_dump.py` incrementally, testing each piece before moving on. Start with `ENTITY=event` (smallest, fastest feedback).

**Step A — Configuration and setup**
- [x] Read `ENTITY` from `os.environ` (fail fast with `KeyError` if missing)
- [x] Define constants: `DUMP_BASE_URL`, `BUCKET_NAME`, `BQ_DATASET`, `CHUNK_SIZE_MB` (configurable, default 100 MB)
- [x] GCS path prefix: `mb-dump/{entity}/{dump_date}/` (not the bucket root — keeps bulk separate from incremental)
- [x] Make `BUCKET_NAME`, `BQ_DATASET`, `BQ_PROJECT`, and `CHUNK_SIZE_MB` configurable via env vars with sensible defaults
- [x] Set up `logging` (not `print()`) — `basicConfig` with timestamps, write to `sys.stdout`
- [x] Write `get_latest_dump_date()` — `GET` the `LATEST` file, return the date string. Use `raise_for_status()` and `timeout`.

> **Study**: [Python `logging` module](https://docs.python.org/3/howto/logging.html)

**Step B — Download the dump**
- [x] Write `download_dump(url)` — download the tar.xz to a temp file, return its path
- [x] Use `requests.get(url, stream=True)` + `iter_content()` to download in chunks without loading the whole file into memory
- [x] Use `tempfile.NamedTemporaryFile(delete=False)` so the file persists after the `with` block closes
- [x] Log download size and elapsed time
- [x] Test: run just this function, verify the temp file exists and has the right size

> **Study**: [Python `requests` — streaming downloads](https://docs.python-requests.readthedocs.io/en/latest/user/advanced/#streaming-requests) | [Python `tempfile`](https://docs.python.org/3/library/tempfile.html)

**Step C — Extract, wrap, and upload chunks to GCS**
- [x] Write `upload_chunk(bucket, chunk_num, dump_date)` — join lines with `\n`, upload as a blob
- [x] GCS blob path: `mb-dump/{entity}/{dump_date}/{entity}_{chunk_num:03d}.jsonl` (zero-padded)
- [x] Write `create_json_line(line, load_time, chunk_num, dump_date)` — parse raw JSON, wrap under `json_data` with audit metadata
- [x] Write `extract_and_upload(dump_path, dump_date)` — open the tar, find `mbdump/{ENTITY}`, iterate lines
- [x] Track accumulated bytes per chunk using wrapped line size (`len(json_line)`). Flush to GCS when `>= CHUNK_SIZE`
- [x] Reset the byte counter and line buffer after each flush
- [x] Don't forget the leftover chunk after the loop ends
- [x] Return total line count for later validation
- [x] Clean up the temp file in a `finally` block (use `os.unlink()`)
- [x] Test: run with event, verify chunks appear in GCS with expected sizes

> **Study**: [GCS Python client](https://cloud.google.com/storage/docs/reference/libraries#client-libraries-install-python) — `Blob.upload_from_string()`

**Step D — Load GCS chunks into BigQuery**
- [x] Write `load_to_bigquery(dump_date, rows_uploaded)` — load all chunks into a BigQuery table
- [x] Source URI: `gs://{BUCKET_NAME}/mb-dump/{ENTITY}/{dump_date}/*.jsonl` (wildcard loads all chunks in one job)
- [x] Define an explicit schema matching the wrapped JSONL structure. Do NOT use `autodetect` — the fixed schema is intentional (see 2.2)
- [x] Configure `LoadJobConfig`: `source_format=NEWLINE_DELIMITED_JSON`, `write_disposition=WRITE_TRUNCATE`, explicit schema
- [x] Audit columns populated at wrapping time in `create_json_line()` — restructuring the JSONL before upload was the chosen approach
- [x] `_raw_loaded_at` populated via post-load `UPDATE` (BigQuery `default_value_expression` does not apply during `load_table_from_uri` with `WRITE_TRUNCATE`)
- [x] Handle entity names with hyphens — BigQuery tables can't have hyphens (e.g. `release-group` → `release_group`). Tables named `{entity}_raw`.
- [x] Call `load_table_from_uri()`, then `.result()` to block until the job completes
- [x] After loading, query the table's row count and compare to `rows_uploaded`. Log a warning on mismatch. Validation skipped when `rows_uploaded` is not available (rerun scenario).
- [x] Test: run the full pipeline with event, verify the table exists in BigQuery with the right schema and row count

> **Study**: [BigQuery `load_table_from_uri`](https://cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.client.Client#google_cloud_bigquery_client_Client_load_table_from_uri)
>
> **Lesson learned**: `default_value_expression` on `SchemaField` only applies when the table already exists before the load job. With `WRITE_TRUNCATE`, the table is recreated during the load, so defaults are not applied. Use a post-load `UPDATE` instead.

**Step E — Skip check**
- [x] Before downloading, check if blobs already exist at `gs://bucket/mb-dump/{entity}/{dump_date}/`
- [x] If files exist: skip download/upload but still run BigQuery load (safe to rerun after failed BQ load)
- [x] To fully rerun: manually delete the GCS files first, then run the script again

**Step F — Wire it all together**
- [x] Write `main()` — orchestrates: skip check → download/upload (if needed) → BigQuery load (always)
- [x] Add `if __name__ == "__main__"` guard
- [x] Log total elapsed time at the end
- [x] Add a module docstring documenting usage and env vars

### 2.4 Test with All Entities

- [x] Run with `ENTITY=event` (~42 MB) — fast feedback, end-to-end validation
- [x] Run with `ENTITY=label` (~161 MB) — intermediate size
- [x] Run with `ENTITY=release-group` (~1 GB) — tests chunking more thoroughly
- [x] Run with `ENTITY=artist` (~2 GB compressed) — stress test. Verify temp file cleanup, chunking, and BigQuery load
- [x] Verify row counts in BigQuery against [MusicBrainz statistics](https://musicbrainz.org/statistics)

### 2.5 Package and Deploy on Cloud Run

> **Note**: Source-based deployment (`--source`) was attempted but Cloud Build's internal provisioning returned NOT_FOUND errors despite the API being enabled. Switched to building images locally with Docker and pushing to Artifact Registry.

- [x] Create a `Dockerfile` in `scripts/` — multi-stage build (builder installs deps into a venv, runtime copies only the venv + script, no pip/build tools in final image)
- [x] Create `.dockerignore` in `scripts/` to exclude Procfile, .gcloudignore, __pycache__
- [x] Add `artifact_registry.tf` to Terraform — Docker-format repo `cloud-run-images` in `us-central1`
- [x] Remove `roles/run.sourceDeveloper` from IAM (no longer needed without `--source`)
- [x] Run `terraform apply` to create the Artifact Registry repo
- [x] Authenticate Docker with Artifact Registry: `gcloud auth configure-docker us-central1-docker.pkg.dev`
- [x] Build and push the image to `us-central1-docker.pkg.dev/is-rock-alive/cloud-run-images/load-dump`
- [x] Deploy with `gcloud run jobs deploy --image` (2 vCPU / 8 GiB, pipeline SA). Initially tried 1 vCPU / 4 GiB but the `artist` dump (~2 GB compressed) caused OOM kills (signal 9) — tar.xz decompression + JSON wrapping + 250 MB chunk buffer exceeded 4 GiB.
- [x] Execute all entities (`event`, `label`, `release-group`, `artist`), verify GCS and BigQuery

**Build and push:**
```bash
docker build -t us-central1-docker.pkg.dev/is-rock-alive/cloud-run-images/load-dump scripts/
docker push us-central1-docker.pkg.dev/is-rock-alive/cloud-run-images/load-dump
```

**Deploy command:**
```bash
gcloud run jobs deploy load-dump \
  --image us-central1-docker.pkg.dev/is-rock-alive/cloud-run-images/load-dump:latest \
  --cpu 2 \
  --memory 8Gi \
  --task-timeout 90m \
  --service-account pipeline-sa@is-rock-alive.iam.gserviceaccount.com \
  --region us-central1
```

**Execute per entity:**
```bash
gcloud run jobs execute load-dump \
  --update-env-vars ENTITY=event,BQ_PROJECT=is-rock-alive,CHUNK_SIZE_MB=250 \
  --region us-central1
```

> **Study**: [Cloud Run Jobs](https://cloud.google.com/run/docs/create-jobs) | [Deploying container images](https://cloud.google.com/run/docs/deploying) | [Executing jobs](https://cloud.google.com/run/docs/execute/jobs) | [Artifact Registry Docker quickstart](https://cloud.google.com/artifact-registry/docs/docker/store-docker-container-images)
>
> **CPU-to-memory constraints** (Cloud Run hard limits):
>
> | CPU | Max memory |
> |-----|-----------|
> | 1 vCPU | 4 GiB |
> | 2 vCPU | 8 GiB |
> | 4 vCPU | 16 GiB |
> | 8 vCPU | 32 GiB |

---

## Phase 3: Data Transformation with dbt

**Why dbt?** dbt (data build tool) brings software engineering practices to SQL transformations: version control, modularity, testing, documentation, and dependency management. Instead of writing one giant SQL script, you write modular models that dbt compiles and runs in dependency order. It's the industry standard for the "T" in ELT.

> **Study**: [dbt Fundamentals course](https://courses.getdbt.com/courses/fundamentals) — **free official course**, highly recommended. Covers models, tests, documentation, and sources.
>
> **Study**: [dbt best practices](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview) — the official "How we structure our dbt projects" guide. The staging/trusted/semantic layers follow this pattern.
>
> **Study**: [dbt and BigQuery setup](https://docs.getdbt.com/docs/core/connect-data-platform/bigquery-setup)

### 3.1 Initialize dbt Project
- [ ] Run `dbt init musicbrainz` inside the project directory
- [ ] Configure `profiles.yml` for BigQuery connection (OAuth via Application Default Credentials)
- [ ] Project structure:
  ```
  dbt/
    dbt_project.yml
    profiles.yml          # gitignored, or use env vars
    models/
      staging/            # 1:1 with raw tables, clean + type
      trusted/            # business logic, dedup, joins
      semantic/           # final tables for dashboards
    tests/                # custom data tests
    macros/               # reusable SQL macros
    seeds/                # static reference data (genre mappings)
  ```

> **Why this three-layer structure?**
> - **Staging**: one model per raw table, handles only cleaning (renaming, casting, filtering nulls). No business logic. Materialized as views because they're lightweight wrappers.
> - **Trusted**: business logic lives here — deduplication, joins, dimensional modeling. These are your "source of truth" tables.
> - **Semantic**: pre-aggregated tables optimized for specific dashboard queries. Keeps Looker Studio fast by avoiding complex JOINs at query time.

### 3.2 Staging Models (raw -> staging)

**Key change from the JSON column approach**: Since raw tables store the full JSON object in a `json_data` column (see 2.2), staging models are responsible for extracting, typing, and naming all fields. Use `JSON_VALUE(json_data, '$.field')` for scalar values and `JSON_EXTRACT_ARRAY(json_data, '$.field')` for arrays. This is where all schema interpretation happens, including computing `_row_hash` via `SHA256(TO_JSON_STRING(json_data))`.

- [ ] `stg_artists` — extract fields from `json_data` JSON column (`JSON_VALUE` for scalars, `JSON_EXTRACT_ARRAY` for tags/aliases), cast types, rename columns, deduplicate by latest record per MBID, compute `_row_hash`
- [ ] `stg_release_groups` — extract from JSON, normalize release types, extract year from date
- [ ] `stg_labels` — extract from JSON, clean label data
- [ ] `stg_events` — extract from JSON, parse event dates and types
- [ ] `stg_artist_tags` — extract and flatten tag array from JSON, filter for genre-like tags
- [ ] `stg_release_group_tags` — same for release groups
- [ ] Materialization: `view` (lightweight, always fresh)

> **Why views for staging?** Views don't store data — they're computed on read. Since staging models are wrappers over raw, there's no performance benefit to materializing them as tables. This saves storage cost and ensures staging always reflects the latest raw data.
>
> **Study**: [dbt materializations](https://docs.getdbt.com/docs/build/materializations) — view, table, incremental, and ephemeral.
>
> **Study**: [BigQuery STRUCT and ARRAY types](https://cloud.google.com/bigquery/docs/nested-repeated) — how BigQuery handles nested/repeated data natively. Important for deciding whether to flatten nested MusicBrainz fields.
>
> **Study**: [Querying JSON data in BigQuery](https://cloud.google.com/bigquery/docs/json-data) — `JSON_VALUE`, `JSON_QUERY`, `JSON_EXTRACT_ARRAY` for parsing the raw JSON column in staging models.

### 3.3 Seeds (Genre Mapping)

**Why seeds for genre mapping?** MusicBrainz uses free-form tags, not a controlled genre vocabulary. "hard rock", "Hard Rock", "classic rock", "progressive rock" are all separate tags. A seed CSV lets you define a standardized mapping (tag -> parent genre) that lives in version control and can be reviewed/updated like code.

- [ ] `genre_mapping.csv` — mapping of raw MusicBrainz tags to standardized genre categories (e.g., map "hard rock", "classic rock", "alternative rock" -> parent "Rock")
- [ ] `release_type_mapping.csv` — if needed for normalization

> **Study**: [dbt seeds](https://docs.getdbt.com/docs/build/seeds) — when to use seeds vs. source tables. Seeds are for small, static reference data that changes rarely.

### 3.4 Trusted Models (staging -> trusted)

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

> **Why bridge tables?** An artist can have multiple genres, and a genre can have multiple artists — that's a many-to-many relationship. Bridge tables resolve this by storing one row per artist-genre pair.
>
> **Study**: [Kimball's dimensional modeling](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/) — star schemas, slowly changing dimensions, and fact table design.
>
> **Study**: [dbt incremental models](https://docs.getdbt.com/docs/build/incremental-models) — for large tables, only process new/changed rows instead of rebuilding.

### 3.5 Semantic Models (trusted -> semantic)
- [ ] `rock_artists_by_year` — count of rock artists with first release per year
- [ ] `rock_albums_by_year` — count of rock release groups per year
- [ ] `rock_albums_by_subgenre_year` — breakdown by rock subgenres over time
- [ ] `top_rock_labels_by_decade` — most prolific rock labels per decade
- [ ] `rock_events_timeline` — rock events over time (festivals, concerts)
- [ ] `genre_evolution` — how genre tag usage changes over time
- [ ] Materialization: `table`

> **Why pre-aggregate?** BI tools perform best when they query pre-aggregated tables rather than running complex JOINs and GROUP BYs on the fly. These semantic models are the "contract" between your data warehouse and your dashboard.

### 3.6 dbt Tests

**Why test data?** Bad data is silent — a broken JOIN produces zero rows, not an error. dbt tests catch issues like duplicate primary keys, null values in required columns, and broken foreign key relationships.

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

---

## Phase 4: Data Ingestion - Incremental API Loads

**Why incremental loads?** MusicBrainz is a living database — new artists debut, albums get released, and metadata gets corrected daily. Incremental loads keep your warehouse current without re-ingesting the entire dump each time.

**Why dlt?** For the incremental pipeline, dlt's strengths shine: built-in pagination, rate limiting, watermark tracking, and schema evolution. These are exactly the problems you'd otherwise have to solve manually for an ongoing API integration.

> **Study**: [Change Data Capture patterns](https://www.confluent.io/learn/change-data-capture/) — understand CDC concepts (watermarks, timestamps, event logs). The MusicBrainz API doesn't offer true CDC, so you'll use timestamp-based watermarks.
>
> **Study**: [dlt documentation](https://dlthub.com/docs/intro) — getting started with dlt for data ingestion.

### 4.1 Understand MusicBrainz API
- [ ] Read API docs: https://musicbrainz.org/doc/MusicBrainz_API
- [ ] Rate limit: 1 request/second (respect this strictly with a custom User-Agent)
- [ ] Register your app and set a descriptive User-Agent header
- [ ] Key endpoints:
  - `GET /ws/2/artist?query=*&fmt=json&offset=N&limit=100`
  - `GET /ws/2/release-group?query=*&fmt=json`
  - Browse endpoints with `inc=` for related data (tags, ratings)

> **Why respect rate limits?** MusicBrainz is a community-run non-profit. Exceeding rate limits gets your IP banned and hurts the service for everyone.
>
> **Study**: [MusicBrainz API rate limiting](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting)
>
> **Study**: [MusicBrainz API search syntax](https://musicbrainz.org/doc/MusicBrainz_API/Search) — Lucene query syntax for filtering entities.

### 4.2 Build Incremental Ingestion with dlt

**Why watermarks?** A watermark is a bookmark that says "I've ingested everything up to this timestamp." Each run picks up from the last watermark, processes new/updated records, then advances the watermark.

- [ ] Write `scripts/incremental_ingest.py` using dlt:
  - Query the MusicBrainz API for recently updated entities
  - Write responses as JSONL to `gs://<PROJECT_ID>-raw/incremental/<entity>/<date>/`
  - dlt stages files through `gs://<PROJECT_ID>-raw/dlt-staging/` before loading to BigQuery
  - Track watermarks (last sync timestamp) via dlt state
  - Handle pagination, retries, and rate limiting
  - Disable dlt normalization — raw data lands as-is, dbt owns all transformations
- [ ] Target entities: artists, release_groups, labels, events
- [ ] Schedule: daily incremental pulls

> **Why disable dlt normalization?** Keeping all transformation logic in dbt (staging layer) avoids splitting transformation across two tools. dlt handles extraction and loading only.
>
> **Why write to GCS before BigQuery?** This is the ELT pattern: raw data always lands in the lake (GCS) first. If a BigQuery load fails, you don't need to re-fetch from the API.
>
> **Study**: [dlt normalization docs](https://dlthub.com/docs/general-usage/schema#data-normalizer) — how to configure or disable normalization.
>
> **Study**: [ELT vs. ETL](https://www.getdbt.com/analytics-engineering/elt-vs-etl) — why modern pipelines load raw data first and transform inside the warehouse.

### 4.3 Load Incremental Data to BigQuery
- [ ] Append new records to `raw.<entity>` tables (WRITE_APPEND)
- [ ] Use the same raw table schema as bulk load: `json_data` (JSON) + audit columns (`_source_file`, `_source_system`, `_batch_id`, `_landing_loaded_at`, `_raw_loaded_at`). This keeps both ingestion paths writing to the same tables with the same structure.
- [ ] Deduplication happens in the dbt staging layer (latest record per MBID, using `_loaded_at` to determine recency)

> **Why append instead of upsert at the raw layer?** Keeping raw as append-only preserves history and keeps ingestion simple. All 3 versions of an artist from 3 daily loads are kept in raw. The dbt staging layer deduplicates by taking the latest record per MBID.
>
> **Why the same schema?** Bulk and incremental loads write to the same raw tables. A uniform schema (`data` + audit columns) means dbt staging models don't need to handle two different source structures.

### 4.4 Deploy to Cloud Run
- [ ] Same local Docker build + Artifact Registry push pattern as Phase 2
- [ ] Deploy as `musicbrainz-incremental` Cloud Run Job
- [ ] Test with a manual execution before wiring up to Airflow

---

## Phase 5: Orchestration with Airflow

**Why Airflow?** Data pipelines have dependencies: you can't transform data that hasn't been ingested yet. Airflow lets you define these dependencies as Directed Acyclic Graphs (DAGs), handles scheduling, retries, alerting, and provides a UI to monitor runs.

> **Study**: [Airflow core concepts](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/index.html) — DAGs, tasks, operators, executors, XComs.
>
> **Study**: [Airflow best practices](https://airflow.apache.org/docs/apache-airflow/stable/best-practices.html) — common pitfalls.
>
> **Study**: [Astronomer's Airflow guides](https://www.astronomer.io/guides/) — practical tutorials on operators, connections, and patterns.

### 5.1 Local Airflow with Docker (Development)

**Why start local?** A local Airflow instance in Docker is free and gives you the same DAG authoring experience as production. Once your DAGs are stable, you deploy to a GCE VM.

- [ ] Create `docker-compose.yml` for local Airflow (use the [official Airflow Docker Compose](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html))
- [ ] Mount local `dags/` and `scripts/` directories into the container
- [ ] Configure Airflow to use your GCP service account for BigQuery/GCS access
- [ ] Verify the Airflow UI is accessible at `localhost:8080`

> **Study**: [Running Airflow in Docker](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html) — official Docker Compose setup guide.

### 5.2 DAG Structure
```
dags/
  musicbrainz_initial_load.py      # One-time DAG for bulk load
  musicbrainz_daily_incremental.py # Daily: ingest -> load -> transform
```

### 5.3 Daily Incremental DAG

**Why this task order?** Each step depends on the previous one completing successfully. Airflow enforces this — if ingestion fails, it won't attempt the transform, preventing cascade failures.

- [ ] Task flow:
  1. `ingest_and_load` — CloudRunExecuteJobOperator: trigger the `musicbrainz-incremental` Cloud Run Job
  2. `dbt_run` — BashOperator: `dbt run` (runs locally on the Airflow VM)
  3. `dbt_test` — BashOperator: `dbt test` (runs locally on the Airflow VM)
  4. `notify_on_failure` — email or Slack alert on failure
- [ ] Schedule: `@daily` (or `0 6 * * *` for 6 AM UTC)
- [ ] Retries: 2, retry delay: 5 minutes

### 5.4 Initial Load DAG
- [ ] One-time trigger (manual) DAG for the bulk dump load
- [ ] Same structure but with WRITE_TRUNCATE and full dbt run

### 5.5 Test Locally
- [ ] Place DAGs in the `dags/` directory mounted to Docker
- [ ] Test each task individually with `airflow tasks test <dag_id> <task_id> <date>`
- [ ] Verify full DAG runs in the Airflow UI

### 5.6 Provision Airflow VM (Production)

**Why a GCE VM?** Cloud Composer (managed Airflow on GKE) costs ~$300-400/mo minimum — overkill for this project. A single e2-small VM with Docker Compose costs ~$15-30/mo always-on, or ~$1-2/mo if kept stopped when idle (disk-only charges). The VM also runs dbt (dbt just compiles SQL and sends it to BigQuery — no heavy local processing, e2-small handles it fine).

- [ ] Add `airflow_vm.tf` to Terraform:
  - e2-small instance in `us-central1`
  - Attach the pipeline service account
  - Startup script to install Docker, Docker Compose, and dbt-core + dbt-bigquery
  - Firewall rule to allow port 8080 (Airflow UI) from your IP only
- [ ] `terraform apply` to provision the VM
- [ ] Create a deployment script to sync DAGs and scripts to the VM
- [ ] SSH into the VM and run Airflow via Docker Compose
- [ ] Configure Airflow connections to use the VM's attached service account
- [ ] Configure VM cost optimization:
  - **Manual start/stop**: `gcloud compute instances start/stop` for dev/demo
  - **GCE instance schedule**: auto-start/stop during pipeline windows (e.g., 6-8 AM UTC)

> **Study**: [GCE instance creation with Terraform](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_instance)
>
> **Study**: [GCE instance schedules](https://cloud.google.com/compute/docs/instances/schedule-instance-start-stop) — auto-start/stop VMs to save costs.
>
> **Security note**: Restrict Airflow UI access via firewall rules (allow only your IP). For extra security, consider IAP (Identity-Aware Proxy) to tunnel access without exposing ports publicly.

---

## Phase 6: Dashboards with Looker Studio

**Why Looker Studio?** It's free, natively integrates with BigQuery, and is good enough for most analytics dashboards. For a learning project, it lets you focus on the data platform rather than self-hosting a BI tool.

> **Study**: [Looker Studio tutorial](https://support.google.com/looker-studio/answer/9171315) — getting started guide.
>
> **Study**: [Connecting BigQuery to Looker Studio](https://support.google.com/looker-studio/answer/6370296)
>
> **Study**: [Dashboard design principles](https://www.storytellingwithdata.com/) — "Storytelling with Data" by Cole Nussbaumer Knaflic.

### 6.1 Connect Looker Studio to BigQuery
- [ ] Go to https://lookerstudio.google.com
- [ ] Create a new data source -> BigQuery -> select `semantic` dataset
- [ ] Add each semantic table as a data source

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

**Why CI/CD?** Continuous Integration / Continuous Deployment automates testing and deployment. When you push code, CI runs linting and tests; when you merge to main, CD deploys changes.

> **Study**: [GitHub Actions quickstart](https://docs.github.com/en/actions/quickstart) — workflows, jobs, steps, and triggers.
>
> **Study**: [Terraform CI/CD with GitHub Actions](https://developer.hashicorp.com/terraform/tutorials/automation/github-actions) — official HashiCorp tutorial.
>
> **Study**: [dbt CI/CD](https://docs.getdbt.com/docs/deploy/continuous-integration) — running dbt in CI against a dev dataset.

### 7.1 Workload Identity Federation

**Why WIF?** In CI/CD, GitHub Actions needs to authenticate to GCP. Workload Identity Federation lets GitHub Actions impersonate the Terraform SA with short-lived tokens — no long-lived JSON key files to store as secrets.

- [ ] Configure the trust relationship between GCP and GitHub
- [ ] Set up the GitHub Actions workflow to authenticate via WIF

> **Study**: [Workload Identity Federation](https://cloud.google.com/iam/docs/workload-identity-federation) — how external workloads authenticate to GCP without key files.

### 7.2 Terraform CI/CD

**Why plan on PR, apply on merge?** Running `terraform plan` on a PR lets reviewers see exactly what will change. Applying only on merge ensures only reviewed changes reach production.

- [ ] On PR: `terraform fmt -check`, `terraform validate`, `terraform plan`
- [ ] On merge to main: `terraform apply -auto-approve`
- [ ] Store project config in GitHub Secrets / Variables

### 7.3 dbt CI/CD
- [ ] On PR: `dbt build --target dev` (runs models + tests against a dev dataset)
- [ ] On merge to main: optionally trigger a production dbt run
- [ ] Lint SQL with `sqlfluff` (BigQuery dialect)

> **Study**: [sqlfluff](https://docs.sqlfluff.com/en/stable/) — SQL linter and formatter.

### 7.4 Python CI/CD
- [ ] Lint with `ruff`
- [ ] Unit tests with `pytest` for ingestion scripts

---

## Phase 8: Monitoring, Cost Control & Hardening

**Why monitoring?** Pipelines fail silently — an API endpoint changes, a schema drifts, a BigQuery job times out. Without monitoring, you might not notice for days that your dashboard is showing stale data.

> **Study**: [GCP Cloud Monitoring](https://cloud.google.com/monitoring/docs/monitoring-overview) — metrics, alerts, and dashboards.
>
> **Study**: [BigQuery cost best practices](https://cloud.google.com/bigquery/docs/best-practices-costs) — cost optimization and query performance.

### 8.1 Cost Management
- [ ] Set up billing budget alerts at $25, $50, $75
- [ ] Use BigQuery on-demand pricing (first 1 TB/mo queries free)
- [ ] Set BigQuery per-user query quotas to prevent runaway costs
- [ ] Use GCS lifecycle rules to move old raw data to Nearline/Coldline
- [ ] Review the [GCP Pricing Calculator](https://cloud.google.com/products/calculator)

### 8.2 Monitoring
- [ ] Set up Airflow email alerts on DAG failures
- [ ] Create a dbt freshness check (`dbt source freshness`) in the daily DAG
- [ ] Monitor BigQuery slot usage and query costs

### 8.3 Security
- [ ] Use Secret Manager for any API keys or credentials
- [ ] Principle of least privilege on all service accounts
- [ ] Enable audit logging on the GCP project

> **Study**: [GCP security best practices](https://cloud.google.com/docs/enterprise/best-practices-for-enterprise-organizations#securing-your-environment)

---

## Execution Order Summary

| Order | Phase | Depends On |
|-------|-------|------------|
| 1 | Phase 0: Bootstrap | Nothing |
| 2 | Phase 1: Terraform Infrastructure | Phase 0 |
| 3 | Phase 2: Bulk Data Ingestion | Phase 1 |
| 4 | Phase 3.1-3.3: dbt Setup + Staging + Seeds | Phase 2 |
| 5 | Phase 3.4-3.6: dbt Curated + Analytics + Tests | Phase 3.3 |
| 6 | Phase 4: Incremental API Ingestion | Phase 2 |
| 7 | Phase 5: Airflow Orchestration | Phase 3, 4 |
| 8 | Phase 6: Looker Studio Dashboards | Phase 3.5 |
| 9 | Phase 7: CI/CD | Phase 1, 3 |
| 10 | Phase 8: Monitoring & Hardening | All above |

---

## Recommended Learning Path

Before diving into implementation, study these topics in order. You don't need to finish everything before starting — but having the mental model helps.

### Foundations (before Phase 0)
1. [GCP Resource Hierarchy](https://cloud.google.com/resource-manager/docs/cloud-platform-resource-hierarchy) — projects, IAM, billing
2. [GCP IAM overview](https://cloud.google.com/iam/docs/overview) — how permissions work
3. [Terraform GCP tutorial](https://developer.hashicorp.com/terraform/tutorials/gcp-get-started) — hands-on

### Data Engineering Concepts (before Phase 2)
4. [Medallion architecture](https://www.databricks.com/glossary/medallion-architecture) — the layered data pattern
5. [ELT vs. ETL](https://www.getdbt.com/analytics-engineering/elt-vs-etl) — why we load first, transform second
6. [Kimball dimensional modeling](https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/) — star schemas, facts, and dimensions

### Tool-Specific (when you reach the relevant phase)
7. [dbt Fundamentals free course](https://courses.getdbt.com/courses/fundamentals) — 4-5 hours, covers everything you need
8. [Airflow core concepts](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/index.html) — DAGs, operators, scheduling
9. [BigQuery best practices](https://cloud.google.com/bigquery/docs/best-practices-performance-overview) — partitioning, clustering, query optimization

### Books (optional deep dives)
10. *Fundamentals of Data Engineering* by Joe Reis & Matt Housley — comprehensive modern DE book
11. *The Data Warehouse Toolkit* by Ralph Kimball — the bible for dimensional modeling
12. *Storytelling with Data* by Cole Nussbaumer Knaflic — making dashboards useful
