# FraudGuard — End-to-End MLOps Pipeline

> XGBoost fraud model that retrains itself on drift: **train → register → serve → monitor → auto-retrain**  
> Stack: MLflow · DVC · Feast · Redis · BentoML · Evidently · Prometheus · Grafana · Argo Rollouts · Vertex AI · GCP

---

## Architecture

```
                         ┌─────────────────────────────────────────────────┐
                         │              GitHub Actions CI/CD                │
                         │  drift-check (6h) → retrain → register → deploy │
                         └───────────────┬─────────────────────────────────┘
                                         │
         ┌───────────────────────────────▼──────────────────────────────────┐
         │                        MLflow Registry                            │
         │          train() → log metrics → register → promote              │
         └───────────────────────────────┬──────────────────────────────────┘
                                         │  model artifacts (GCS)
         ┌────────────────────┐          │          ┌──────────────────────┐
         │   Feast + Redis    │◄─────────┘          │  Evidently           │
         │  (feature store)   │                     │  (drift detection)   │
         │  velocity, avg_amt │                     │  ref vs live data    │
         └────────┬───────────┘                     └──────────────────────┘
                  │ features (<2ms)
         ┌────────▼───────────────────────────────────────────────────────┐
         │              FastAPI Serving (port 8000)                        │
         │   POST /predict → fetch features → XGBoost → fraud_score       │
         │   GET  /metrics → Prometheus exposition                         │
         └────────────────────────────────────────────────────────────────┘
                  │ metrics scrape
         ┌────────▼───────────────────────────────────────────────────────┐
         │         Prometheus + Grafana (port 9090 / 3000)                 │
         │   p99 latency · fraud rate · request volume · score dist       │
         └────────────────────────────────────────────────────────────────┘
```

---

## Day-by-Day Build

### Day 1 — Train & Track
- Synthetic 100k-row fraud dataset (1% fraud rate, realistic feature distributions)
- XGBoost with `scale_pos_weight=99` (handles 99:1 class imbalance)
- MLflow experiment tracking: PR-AUC, ROC-AUC, F1, feature importance
- DVC pipeline: `generate → train → detect_drift`
- GCS remote state for data versioning

### Day 2 — Serve & Monitor
- FastAPI endpoint: `POST /predict` with Prometheus metrics
- Evidently drift detection against training reference snapshot
- Feast feature store with Redis online store (velocity, avg spend pre-computed)
- Grafana dashboard: p99 latency SLO, fraud rate, score distribution

### Day 3 — Automate the Loop
- GitHub Actions: drift check every 6h → retrain → register → canary deploy
- Argo Rollouts: 10% canary → p99 analysis gate → promote to 100%
- Vertex AI Pipelines: one-shot GCP run for resume screenshot
- Terraform: GCS bucket + Artifact Registry + CI/CD service account

---

## Quickstart (local)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Generate data
python src/train/generate_data.py

# 3. Start MLflow + Redis
docker compose up mlflow redis -d

# 4. Train model
python src/train/train.py

# 5. Promote to Production
python scripts/promote_model.py --stage Production

# 6. Start serving
docker compose up fraudguard-serve -d

# 7. Test prediction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{"transaction_id":"txn_001","amount":9999,"hour_of_day":2,"day_of_week":1,
       "merchant_category":3,"distance_from_home_km":200,"velocity_1h":8,
       "velocity_24h":25,"avg_spend_7d":50,"is_international":1,"card_present":0}'

# 8. Run drift detection (exit 1 = drift detected)
python src/monitoring/drift_detector.py

# 9. View Grafana
open http://localhost:3000  # admin/admin
```

---

## Running Tests

```bash
pytest tests/ -v
```

---

## DVC Pipeline

```bash
dvc repro          # run full pipeline: generate → train → drift
dvc params diff    # compare params across runs
dvc metrics show   # show tracked metrics
```

---

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Model | XGBoost | Best PR-AUC + retrainability on tabular fraud data |
| Class imbalance | `scale_pos_weight` | No oversampling memory overhead |
| Primary metric | PR-AUC | Accuracy is misleading at 1% fraud rate |
| Drift detection | Evidently feature drift | Ground-truth labels delayed by days |
| Feature store | Feast + Redis | <2ms online serving, no managed cost |
| Serving | FastAPI + MLflow | Load latest Production model at startup |
| Canary | Argo Rollouts | p99 gate before full traffic shift |

See [`ADRs/`](ADRs/) for full decision records.

---

## GCP Deploy (one-shot)

```bash
cd infra/terraform && terraform init && terraform apply
# Then: Vertex AI Pipelines run for screenshot
```

---

## Production Gap (documented)
- Multi-region serving and HA not implemented (scope: portfolio demo)
- Ground-truth feedback loop (when fraud confirmed → retrain with real labels) not wired
- Full pen-testing and chaos engineering out of scope
