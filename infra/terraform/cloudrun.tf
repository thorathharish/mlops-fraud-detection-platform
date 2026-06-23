# Cloud Run serving — one-shot GCP deploy for portfolio screenshot
resource "google_cloud_run_v2_service" "fraudguard_serve" {
  name     = "fraudguard-serve"
  location = var.region

  template {
    service_account = google_service_account.fraudguard_cicd.email

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/fraudguard/fraudguard-serve:latest"

      ports {
        container_port = 8000
      }

      env {
        name  = "MODEL_NAME"
        value = "fraudguard-xgboost"
      }
      env {
        name  = "MODEL_STAGE"
        value = "production"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        initial_delay_seconds = 30
        period_seconds        = 10
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# Allow unauthenticated for demo screenshot
resource "google_cloud_run_v2_service_iam_member" "allow_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.fraudguard_serve.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
