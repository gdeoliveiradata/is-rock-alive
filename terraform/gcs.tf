# Landing zone for JSONL dumps and API responses — immutable copy of ingested data.
# Lifecycle rule moves objects to Nearline after 90 days to reduce storage costs.
resource "google_storage_bucket" "landing_bucket" {
  name                        = "${var.PROJECT_ID}-landing"
  project                     = var.PROJECT_ID
  location                    = var.PROJECT_REGION
  uniform_bucket_level_access = true

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
    condition {
      age = 30
    }
  }
}

# Syncs DAGs and scripts to the Airflow GCE VM.
resource "google_storage_bucket" "pipeline_bucket" {
  name                        = "${var.PROJECT_ID}-pipeline"
  project                     = var.PROJECT_ID
  location                    = var.PROJECT_REGION
  uniform_bucket_level_access = true
}