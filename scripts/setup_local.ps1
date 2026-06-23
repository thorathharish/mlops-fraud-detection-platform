# FraudGuard Local Setup Script (Windows PowerShell)
# Installs all dependencies, generates data, trains model, starts full stack
# Usage: .\scripts\setup_local.ps1

param(
  [switch]$SkipInstall,
  [switch]$SkipTrain,
  [switch]$StackOnly
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== FraudGuard Local Setup ===" -ForegroundColor Cyan
Set-Location $ProjectRoot

# 1. Install Python dependencies
if (-not $SkipInstall -and -not $StackOnly) {
  Write-Host "`n[1/6] Installing Python dependencies..." -ForegroundColor Yellow
  pip install -r requirements.txt --quiet
  Write-Host "  Done." -ForegroundColor Green
}

# 2. Generate synthetic dataset
if (-not $SkipTrain -and -not $StackOnly) {
  Write-Host "`n[2/6] Generating synthetic fraud dataset..." -ForegroundColor Yellow
  python src/train/generate_data.py
  Write-Host "  Done." -ForegroundColor Green
}

# 3. Start MLflow + Redis via Docker Compose
Write-Host "`n[3/6] Starting MLflow and Redis..." -ForegroundColor Yellow
docker compose up mlflow redis -d --wait
Write-Host "  MLflow: http://localhost:5000" -ForegroundColor Green
Write-Host "  Redis:  localhost:6379" -ForegroundColor Green

# 4. Train model
if (-not $SkipTrain -and -not $StackOnly) {
  Write-Host "`n[4/6] Training XGBoost model..." -ForegroundColor Yellow
  $env:MLFLOW_TRACKING_URI = "http://localhost:5000"
  python src/train/train.py
  Write-Host "  Done. View results at http://localhost:5000" -ForegroundColor Green

  Write-Host "`n[4b] Promoting model to production alias..." -ForegroundColor Yellow
  python scripts/promote_model.py --stage production
  Write-Host "  Done." -ForegroundColor Green
}

# 5. Start full stack
Write-Host "`n[5/6] Starting full stack (serving + Prometheus + Grafana)..." -ForegroundColor Yellow
docker compose up fraudguard-serve prometheus grafana -d --wait
Write-Host "  Serving:    http://localhost:8000/docs" -ForegroundColor Green
Write-Host "  Prometheus: http://localhost:9090" -ForegroundColor Green
Write-Host "  Grafana:    http://localhost:3000 (admin/admin)" -ForegroundColor Green

# 6. Run smoke test
Write-Host "`n[6/6] Running smoke test..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
try {
  $fraud_txn = @{
    transaction_id = "smoke_test_001"
    amount = 9999.0; hour_of_day = 2; day_of_week = 6
    merchant_category = 11; distance_from_home_km = 450.0
    velocity_1h = 9; velocity_24h = 28
    avg_spend_7d = 55.0; is_international = 1; card_present = 0
  } | ConvertTo-Json

  $result = (Invoke-WebRequest -Uri "http://localhost:8000/predict" `
    -Method POST -Body $fraud_txn -ContentType "application/json" `
    -UseBasicParsing).Content | ConvertFrom-Json

  Write-Host "  Smoke test PASSED: $($result.transaction_id) -> $($result.decision) (score: $($result.fraud_probability))" -ForegroundColor Green
} catch {
  Write-Host "  Smoke test FAILED: $_" -ForegroundColor Red
}

Write-Host "`n=== Setup Complete ===" -ForegroundColor Cyan
Write-Host @"

Quick links:
  FraudGuard API docs : http://localhost:8000/docs
  MLflow UI           : http://localhost:5000
  Grafana dashboard   : http://localhost:3000  (admin/admin)
  Prometheus          : http://localhost:9090

Run drift detection:
  python src/monitoring/drift_detector.py

Tear down:
  docker compose down
"@
