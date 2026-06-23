# FraudGuard Kind Cluster Setup
# Creates a local Kubernetes cluster and deploys the full stack via Helm
# Usage: .\scripts\setup_kind_cluster.ps1

param(
  [switch]$DestroyFirst,
  [string]$ImageTag = "local"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "=== FraudGuard Kind Cluster Setup ===" -ForegroundColor Cyan

# Destroy existing cluster if requested
if ($DestroyFirst) {
  Write-Host "`nDestroying existing cluster..." -ForegroundColor Yellow
  kind delete cluster --name fraudguard 2>$null
}

# 1. Create kind cluster
Write-Host "`n[1/6] Creating kind cluster..." -ForegroundColor Yellow
$existing = kind get clusters 2>$null
if ($existing -match "fraudguard") {
  Write-Host "  Cluster 'fraudguard' already exists, skipping." -ForegroundColor Gray
} else {
  kind create cluster --config kind-config.yaml
  Write-Host "  Done." -ForegroundColor Green
}

# Set kubectl context
kubectl config use-context kind-fraudguard

# 2. Create namespace + RBAC
Write-Host "`n[2/6] Creating namespace and RBAC..." -ForegroundColor Yellow
kubectl apply -f k8s/manifests/namespace.yaml
kubectl apply -f k8s/manifests/rbac.yaml
Write-Host "  Done." -ForegroundColor Green

# 3. Install Argo Rollouts CRDs + controller
Write-Host "`n[3/6] Installing Argo Rollouts..." -ForegroundColor Yellow
kubectl create namespace argo-rollouts 2>$null
kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml
Write-Host "  Done." -ForegroundColor Green

# 4. Deploy infrastructure (MLflow + Redis)
Write-Host "`n[4/6] Deploying MLflow and Redis..." -ForegroundColor Yellow
kubectl apply -f k8s/manifests/mlflow.yaml
kubectl apply -f k8s/manifests/redis.yaml
kubectl -n fraudguard rollout status deployment/mlflow --timeout=120s
kubectl -n fraudguard rollout status deployment/redis --timeout=60s
Write-Host "  Done." -ForegroundColor Green

# 5. Build and load local Docker image
Write-Host "`n[5/6] Building and loading Docker image into kind..." -ForegroundColor Yellow
docker build -f docker/Dockerfile.serve -t fraudguard-serve:$ImageTag .
kind load docker-image fraudguard-serve:$ImageTag --name fraudguard
Write-Host "  Done." -ForegroundColor Green

# 6. Deploy FraudGuard via Helm
Write-Host "`n[6/6] Deploying FraudGuard via Helm..." -ForegroundColor Yellow
helm upgrade --install fraudguard helm/fraudguard `
  --namespace fraudguard `
  --set image.repository=fraudguard-serve `
  --set image.tag=$ImageTag `
  --set image.pullPolicy=Never `
  --set env.MLFLOW_TRACKING_URI=http://mlflow:5000 `
  --wait --timeout 3m
Write-Host "  Done." -ForegroundColor Green

Write-Host "`n=== Kind Cluster Ready ===" -ForegroundColor Cyan
Write-Host @"

Cluster: fraudguard (kind)

Access services (mapped to localhost via kind extraPortMappings):
  FraudGuard serve : http://localhost:8001
  MLflow           : http://localhost:5001
  Grafana          : http://localhost:3000
  Prometheus       : http://localhost:9090

Check rollout status:
  kubectl -n fraudguard get rollouts
  kubectl argo rollouts get rollout fraudguard-serve -n fraudguard --watch

Tear down:
  kind delete cluster --name fraudguard
"@
