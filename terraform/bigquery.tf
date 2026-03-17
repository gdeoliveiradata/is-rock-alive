# Four datasets following the medallion architecture (raw -> staging -> trusted -> semantic).
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

resource "google_bigquery_dataset" "trusted_dataset" {
  project       = var.PROJECT_ID
  location      = var.PROJECT_REGION
  dataset_id    = "trusted"
  friendly_name = "Trusted Layer Dataset"
  description   = "Dataset containing cleaned, deduplicated, typed tables (dbt models)."
}

resource "google_bigquery_dataset" "semantic_dataset" {
  project       = var.PROJECT_ID
  location      = var.PROJECT_REGION
  dataset_id    = "semantic"
  friendly_name = "Semantic Layer Dataset"
  description   = "Dataset containing final aggregated tables for visualization."
}