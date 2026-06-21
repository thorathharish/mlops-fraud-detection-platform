terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  backend "gcs" {
    bucket = "fraudguard-tf-state"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# GCS bucket for DVC data + MLflow artifacts
resource "google_storage_bucket" "mlops_data" {
  name                        = "${var.project_id}-fraudguard-data"
  location                    = var.region
  force_destroy               = false
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action { type = "Delete" }
    condition { age = 90 }
  }
}

# Artifact Registry for Docker images
resource "google_artifact_registry_repository" "fraudguard" {
  location      = var.region
  repository_id = "fraudguard"
  description   = "FraudGuard Docker images"
  format        = "DOCKER"
}

# Service account for CI/CD
resource "google_service_account" "fraudguard_cicd" {
  account_id   = "fraudguard-cicd"
  display_name = "FraudGuard CI/CD Service Account"
}

resource "google_project_iam_member" "cicd_storage" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.fraudguard_cicd.email}"
}

resource "google_project_iam_member" "cicd_ar" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.fraudguard_cicd.email}"
}

resource "google_project_iam_member" "cicd_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.fraudguard_cicd.email}"
}
