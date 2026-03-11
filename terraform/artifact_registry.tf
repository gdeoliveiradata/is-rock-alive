resource "google_artifact_registry_repository" "docker_repository" {
  location      = var.PROJECT_REGION
  repository_id = "pipelines"
  description   = "Repository of Docker Images for the pipelines."
  format        = "DOCKER"
}