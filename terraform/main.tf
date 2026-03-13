# Remote backend in GCS so state is shared, versioned, and supports locking.
# The backend block only accepts literals — no variables or expressions.
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "7.23.0"
    }
  }
  backend "gcs" {
    bucket = "is-rock-alive-tf-state"
    prefix = "terraform/state"
  }
}

# Authenticates via Application Default Credentials (no JSON key files).
provider "google" {
  project = var.PROJECT_ID
  region  = var.PROJECT_REGION
  zone    = var.PROJECT_ZONE
}