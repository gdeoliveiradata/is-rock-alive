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

provider "google" {
  project = var.PROJECT_ID
  region  = var.PROJECT_REGION
  zone    = var.PROJECT_ZONE
}