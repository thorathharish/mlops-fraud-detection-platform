output "gcs_bucket_name" {
  value = google_storage_bucket.mlops_data.name
}

output "artifact_registry_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/fraudguard"
}

output "cicd_service_account_email" {
  value = google_service_account.fraudguard_cicd.email
}
