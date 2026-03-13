# Values referenced by ingestion scripts, dbt profiles, Cloud Run deployments, and CI/CD.
output "pipeline_sa_email" {
  description = "Email of the Pipeline Service Account."
  value       = google_service_account.pipeline_sa.email
}

output "gcs_raw_bucket_name" {
  description = "Name of the GCS raw bucket."
  value       = google_storage_bucket.raw_bucket.name
}

output "gcs_staging_bucket_name" {
  description = "Name of the GCS staging bucket."
  value       = google_storage_bucket.staging_bucket.name
}

output "gcs_airflow_bucket_name" {
  description = "Name of the GCS Airflow bucket."
  value       = google_storage_bucket.airflow_bucket.name
}

output "bq_raw_dataset_id" {
  description = "Id of the BigQuery raw dataset."
  value       = google_bigquery_dataset.raw_dataset.dataset_id
}

output "bq_staging_dataset_id" {
  description = "Id of the BigQuery staging dataset."
  value       = google_bigquery_dataset.staging_dataset.dataset_id
}

output "bq_curated_dataset_id" {
  description = "Id of the BigQuery curated dataset."
  value       = google_bigquery_dataset.curated_dataset.dataset_id
}

output "bq_analytics_dataset_id" {
  description = "Id of the BigQuery analytics dataset."
  value       = google_bigquery_dataset.analytics_dataset.dataset_id
}