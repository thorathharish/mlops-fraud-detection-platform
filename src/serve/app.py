"""
FastAPI inference endpoint for FraudGuard.
Loads latest production model from MLflow Registry.
Exposes /predict, /health, /metrics (Prometheus).
"""

import os
import time
from contextlib import asynccontextmanager

import mlflow.xgboost
import pandas as pd
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field
from starlette.responses import Response

FEATURE_COLS = [
    "amount", "hour_of_day", "day_of_week", "merchant_category",
    "distance_from_home_km", "velocity_1h", "velocity_24h",
    "avg_spend_7d", "is_international", "card_present",
]

# Prometheus metrics
REQUEST_COUNT = Counter("fraudguard_requests_total", "Total prediction requests", ["result"])
REQUEST_LATENCY = Histogram(
    "fraudguard_request_latency_seconds",
    "Prediction latency",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1.0],
)
FRAUD_SCORE = Histogram(
    "fraudguard_fraud_score",
    "Distribution of fraud probability scores",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

model = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    model_name = os.getenv("MODEL_NAME", "fraudguard-xgboost")
    model_alias = os.getenv("MODEL_STAGE", "production").lower()
    mlflow.set_tracking_uri(tracking_uri)
    model_uri = f"models:/{model_name}@{model_alias}"
    print(f"Loading model from {model_uri}")
    model = mlflow.xgboost.load_model(model_uri)
    print("Model loaded.")
    yield
    model = None


app = FastAPI(title="FraudGuard", version="1.0.0", lifespan=lifespan)


class Transaction(BaseModel):
    transaction_id: str = Field(..., example="txn_0000001")
    amount: float = Field(..., gt=0)
    hour_of_day: int = Field(..., ge=0, le=23)
    day_of_week: int = Field(..., ge=0, le=6)
    merchant_category: int = Field(..., ge=0, le=19)
    distance_from_home_km: float = Field(..., ge=0)
    velocity_1h: int = Field(..., ge=0)
    velocity_24h: int = Field(..., ge=0)
    avg_spend_7d: float = Field(..., ge=0)
    is_international: int = Field(..., ge=0, le=1)
    card_present: int = Field(..., ge=0, le=1)


class PredictionResponse(BaseModel):
    transaction_id: str
    fraud_probability: float
    decision: str
    latency_ms: float


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": model is not None}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict", response_model=PredictionResponse)
def predict(txn: Transaction):
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    t0 = time.perf_counter()
    row = pd.DataFrame([{col: getattr(txn, col) for col in FEATURE_COLS}])
    prob = float(model.predict_proba(row)[0, 1])
    latency_ms = (time.perf_counter() - t0) * 1000

    decision = "BLOCK" if prob >= 0.5 else "ALLOW"
    REQUEST_COUNT.labels(result=decision).inc()
    REQUEST_LATENCY.observe(latency_ms / 1000)
    FRAUD_SCORE.observe(prob)

    return PredictionResponse(
        transaction_id=txn.transaction_id,
        fraud_probability=round(prob, 4),
        decision=decision,
        latency_ms=round(latency_ms, 3),
    )
