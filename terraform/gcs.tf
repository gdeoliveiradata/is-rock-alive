resource "google_storage_bucket" "raw_bucket" {
  name                        = "${var.PROJECT_ID}-raw"
  project                     = var.PROJECT_ID
  location                    = var.PROJECT_REGION
  uniform_bucket_level_access = true

  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
    condition {
      age = 90
    }
  }
}

resource "google_storage_bucket" "staging_bucket" {
  name                        = "${var.PROJECT_ID}-staging"
  project                     = var.PROJECT_ID
  location                    = var.PROJECT_REGION
  uniform_bucket_level_access = true
}

resource "google_storage_bucket" "airflow_bucket" {
  name                        = "${var.PROJECT_ID}-airflow"
  project                     = var.PROJECT_ID
  location                    = var.PROJECT_REGION
  uniform_bucket_level_access = true
}