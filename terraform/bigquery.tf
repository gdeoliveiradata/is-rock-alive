# Four datasets following the medallion architecture (raw -> staging -> curated -> analytics).
# Each layer has independent access controls and clear data lineage.
resource "google_bigquery_dataset" "raw_dataset" {
  project       = var.PROJECT_ID
  location      = var.PROJECT_REGION
  dataset_id    = "raw"
  friendly_name = "Raw Layer Dataset"
  description   = "Dataset containing raw data loaded directly from GCS."
}

resource "google_bigquery_dataset" "staging_dataset" {
  project       = var.PROJECT_ID
  location      = var.PROJECT_REGION
  dataset_id    = "staging"
  friendly_name = "Staging Layer Dataset"
  description   = "Dataset containing intermediate dbt models (views)."
}

resource "google_bigquery_dataset" "curated_dataset" {
  project       = var.PROJECT_ID
  location      = var.PROJECT_REGION
  dataset_id    = "curated"
  friendly_name = "Curated Layer Dataset"
  description   = "Dataset containing cleaned, deduplicated, typed tables (dbt models)."
}

resource "google_bigquery_dataset" "analytics_dataset" {
  project       = var.PROJECT_ID
  location      = var.PROJECT_REGION
  dataset_id    = "analytics"
  friendly_name = "Analytics Layer Dataset"
  description   = "Dataset containing final aggregated tables for visualization."
}