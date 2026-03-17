# Values referenced by ingestion scripts, dbt profiles, Cloud Run deployments, and CI/CD.
output "pipeline_sa_email" {
  description = "Email of the Pipeline Service Account."
  value       = google_service_account.pipeline_sa.email
}

output "gcs_landing_bucket_name" {
  description = "Name of the GCS landing bucket."
  value       = google_storage_bucket.landing_bucket.name
}

output "gcs_pipeline_bucket_name" {
  description = "Name of the GCS pipeline bucket."
  value       = google_storage_bucket.pipeline_bucket.name
}

output "bq_raw_dataset_id" {
  description = "Id of the BigQuery raw dataset."
  value       = google_bigquery_dataset.raw_dataset.dataset_id
}

output "bq_staging_dataset_id" {
  description = "Id of the BigQuery staging dataset."
  value       = google_bigquery_dataset.staging_dataset.dataset_id
}

output "bq_trusted_dataset_id" {
  description = "Id of the BigQuery trusted dataset."
  value       = google_bigquery_dataset.trusted_dataset.dataset_id
}

output "bq_semantic_dataset_id" {
  description = "Id of the BigQuery semantic dataset."
  value       = google_bigquery_dataset.semantic_dataset.dataset_id
}