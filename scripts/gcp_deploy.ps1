# FraudGuard GCP One-Shot Deploy
# Provisions GCP infra via Terraform, builds and pushes image, deploys to Cloud Run
# Usage: .\scripts\gcp_deploy.ps1
# Cost: ~$0 for short-lived deploy (Cloud Run scales to 0, GKE Autopilot billed per pod)

param(
  [string]$Project = "vizualflo-openclaw-prod",
  [string]$Region = "us-central1",
  [switch]$Destroy
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$AR_REPO = "$Region-docker.pkg.dev/$Project/fraudguard"

Write-Host "=== FraudGuard GCP Deploy ===" -ForegroundColor Cyan
Write-Host "Project: $Project  |  Region: $Region" -ForegroundColor Gray

if ($Destroy) {
  Write-Host "`nDestroying GCP resources..." -ForegroundColor Red
  Set-Location infra/terraform
  terraform destroy -auto-approve -var="project_id=$Project" -var="region=$Region"
  Set-Location $ProjectRoot
  Write-Host "Destroyed." -ForegroundColor Green
  exit 0
}

# 1. Bootstrap Terraform state bucket (only needed once)
Write-Host "`n[1/5] Bootstrapping Terraform state bucket..." -ForegroundColor Yellow
$StateBucket = "$Project-fraudguard-tf-state"
$exists = gcloud storage buckets describe "gs://$StateBucket" 2>$null
if (-not $exists) {
  gcloud storage buckets create "gs://$StateBucket" --location=$Region --project=$Project
  Write-Host "  Created state bucket: gs://$StateBucket" -ForegroundColor Green
} else {
  Write-Host "  State bucket already exists." -ForegroundColor Gray
}

# 2. Terraform apply
Write-Host "`n[2/5] Running Terraform..." -ForegroundColor Yellow
Set-Location infra/terraform
$env:GOOGLE_PROJECT = $Project
terraform init -backend-config="bucket=$StateBucket"
terraform apply -auto-approve -var="project_id=$Project" -var="region=$Region"
$AR_URL = terraform output -raw artifact_registry_url
Set-Location $ProjectRoot
Write-Host "  Artifact Registry: $AR_URL" -ForegroundColor Green

# 3. Build and push Docker image
Write-Host "`n[3/5] Building and pushing Docker image..." -ForegroundColor Yellow
gcloud auth configure-docker "$Region-docker.pkg.dev" --quiet
docker build -f docker/Dockerfile.serve -t "$AR_REPO/fraudguard-serve:latest" .
docker push "$AR_REPO/fraudguard-serve:latest"
Write-Host "  Pushed: $AR_REPO/fraudguard-serve:latest" -ForegroundColor Green

# 4. Deploy to Cloud Run
Write-Host "`n[4/5] Deploying to Cloud Run..." -ForegroundColor Yellow
gcloud run deploy fraudguard-serve `
  --image "$AR_REPO/fraudguard-serve:latest" `
  --region $Region `
  --project $Project `
  --platform managed `
  --allow-unauthenticated `
  --memory 1Gi `
  --cpu 1 `
  --set-env-vars "MODEL_NAME=fraudguard-xgboost,MODEL_STAGE=production,MLFLOW_TRACKING_URI=http://mlflow:5000"

$ServiceURL = gcloud run services describe fraudguard-serve `
  --region $Region --project $Project `
  --format "value(status.url)"
Write-Host "  Cloud Run URL: $ServiceURL" -ForegroundColor Green

# 5. Smoke test
Write-Host "`n[5/5] Smoke testing Cloud Run endpoint..." -ForegroundColor Yellow
$fraud_txn = @{
  transaction_id = "gcp_smoke_001"
  amount = 9999.0; hour_of_day = 2; day_of_week = 6
  merchant_category = 11; distance_from_home_km = 450.0
  velocity_1h = 9; velocity_24h = 28
  avg_spend_7d = 55.0; is_international = 1; card_present = 0
} | ConvertTo-Json

try {
  $result = (Invoke-WebRequest -Uri "$ServiceURL/predict" `
    -Method POST -Body $fraud_txn -ContentType "application/json" `
    -UseBasicParsing).Content | ConvertFrom-Json
  Write-Host "  PASSED: $($result.decision) (score: $($result.fraud_probability))" -ForegroundColor Green
} catch {
  Write-Host "  Check manually: $ServiceURL/health" -ForegroundColor Yellow
}

Write-Host "`n=== GCP Deploy Complete ===" -ForegroundColor Cyan
Write-Host @"
  Cloud Run: $ServiceURL
  Artifact Registry: $AR_URL
  MLflow: (running locally — for GKE deploy use setup_kind_cluster.ps1)

REMEMBER to tear down when done to avoid charges:
  .\scripts\gcp_deploy.ps1 -Destroy
"@
