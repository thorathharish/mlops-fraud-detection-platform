locals {
  cluster_name = "fraudguard-cluster"
}

# VPC Network
resource "google_compute_network" "fraudguard_vpc" {
  name                    = "fraudguard-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "fraudguard_subnet" {
  name          = "fraudguard-subnet"
  ip_cidr_range = "10.0.0.0/16"
  region        = var.region
  network       = google_compute_network.fraudguard_vpc.id

  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.1.0.0/16"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.2.0.0/20"
  }
}

# GKE Autopilot cluster
resource "google_container_cluster" "fraudguard" {
  name     = local.cluster_name
  location = var.region

  enable_autopilot = true
  network          = google_compute_network.fraudguard_vpc.id
  subnetwork       = google_compute_subnetwork.fraudguard_subnet.id

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  release_channel {
    channel = "REGULAR"
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  # Disable deletion protection for portfolio teardown
  deletion_protection = false
}

# Workload Identity binding: K8s SA -> GCP SA
resource "google_service_account_iam_member" "workload_identity" {
  service_account_id = google_service_account.fraudguard_cicd.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[fraudguard/fraudguard-serve]"
}
