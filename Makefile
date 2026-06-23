.PHONY: setup generate train promote drift serve test stack-up stack-down demo

# ── Setup ──────────────────────────────────────────────────────────────────
setup:
	pip install -r requirements.txt

# ── Data & Training ────────────────────────────────────────────────────────
generate:
	python src/train/generate_data.py

train:
	MLFLOW_TRACKING_URI=http://localhost:5000 python src/train/train.py

promote:
	MLFLOW_TRACKING_URI=http://localhost:5000 python scripts/promote_model.py --stage production

# ── Drift Detection ────────────────────────────────────────────────────────
drift:
	python src/monitoring/drift_detector.py; \
	  echo "Exit $$?: 0=no drift, 1=drift detected (retrain triggered)"

# ── Serving ────────────────────────────────────────────────────────────────
serve:
	MLFLOW_TRACKING_URI=http://localhost:5000 \
	MODEL_NAME=fraudguard-xgboost \
	MODEL_STAGE=production \
	uvicorn src.serve.app:app --host 0.0.0.0 --port 8000 --reload

# ── Tests ──────────────────────────────────────────────────────────────────
test:
	python -m pytest tests/ -v --tb=short

# ── Docker stack ───────────────────────────────────────────────────────────
stack-up:
	docker compose up mlflow redis prometheus grafana -d

stack-down:
	docker compose down

# ── Full demo run ──────────────────────────────────────────────────────────
demo: generate train promote
	@echo ""
	@echo "=== Model trained and promoted to production ==="
	@echo "Run 'make serve' in another terminal, then 'make drift' to simulate drift"
