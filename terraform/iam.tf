# Runtime SA for Airflow, dbt, Cloud Run Jobs. Separate from the Terraform SA
# to follow least privilege — it only gets the permissions workloads need.
resource "google_service_account" "pipeline_sa" {
  project      = var.PROJECT_ID
  account_id   = "pipeline-sa"
  display_name = "Pipeline Service Account"
}

# Uses google_project_iam_member (additive) instead of google_project_iam_binding
# (authoritative per role) to avoid revoking permissions from other principals
# (user account, Google-managed SAs).
resource "google_project_iam_member" "pipeline_sa_roles" {

  for_each = toset([
    "roles/bigquery.dataEditor",
    "roles/bigquery.jobUser",
    "roles/storage.objectAdmin",
    "roles/compute.instanceAdmin.v1",
    "roles/run.invoker",
    "roles/run.sourceDeveloper",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/iam.serviceAccountUser",
    "roles/artifactregistry.reader"
  ])

  project = var.PROJECT_ID
  role    = each.value
  member  = "serviceAccount:${google_service_account.pipeline_sa.email}"
}