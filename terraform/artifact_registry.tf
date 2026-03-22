# Docker repository for container images built locally and deployed to Cloud Run.
resource "google_artifact_registry_repository" "docker" {
  location      = var.PROJECT_REGION
  repository_id = "cloud-run-images"
  format        = "DOCKER"
  description   = "Container images for Cloud Run jobs"
}
