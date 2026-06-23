"""
BentoML service wrapper for FraudGuard.
Wraps the MLflow-registered XGBoost model as a BentoML service with:
  - Input/output schema validation
  - Prometheus metrics via BentoML runner
  - Batching support

Build & serve:
  bentoml build
  bentoml serve fraudguard_service:latest
"""

import os

import bentoml
import mlflow.xgboost
import numpy as np
import pandas as pd
from bentoml.io import JSON, NumpyNdarray
from pydantic import BaseModel

FEATURE_COLS = [
    "amount", "hour_of_day", "day_of_week", "merchant_category",
    "distance_from_home_km", "velocity_1h", "velocity_24h",
    "avg_spend_7d", "is_international", "card_present",
]


class TransactionInput(BaseModel):
    transaction_id: str
    amount: float
    hour_of_day: int
    day_of_week: int
    merchant_category: int
    distance_from_home_km: float
    velocity_1h: int
    velocity_24h: int
    avg_spend_7d: float
    is_international: int
    card_present: int


class FraudPrediction(BaseModel):
    transaction_id: str
    fraud_probability: float
    decision: str


def save_model_to_bentoml():
    """Pull the production model from MLflow and save it into the BentoML store."""
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(tracking_uri)
    model = mlflow.xgboost.load_model("models:/fraudguard-xgboost@production")
    bento_model = bentoml.xgboost.save_model(
        "fraudguard_xgboost",
        model,
        signatures={"predict_proba": {"batchable": True}},
        metadata={"source": "mlflow", "feature_cols": FEATURE_COLS},
    )
    print(f"Saved to BentoML store: {bento_model.tag}")
    return bento_model.tag


# Load runner from BentoML model store
fraudguard_runner = bentoml.xgboost.get("fraudguard_xgboost:latest").to_runner()

svc = bentoml.Service("fraudguard_service", runners=[fraudguard_runner])


@svc.api(input=JSON(pydantic_model=TransactionInput), output=JSON(pydantic_model=FraudPrediction))
async def predict(txn: TransactionInput) -> FraudPrediction:
    row = pd.DataFrame([{col: getattr(txn, col) for col in FEATURE_COLS}])
    proba = await fraudguard_runner.predict_proba.async_run(row)
    fraud_prob = float(proba[0, 1])
    return FraudPrediction(
        transaction_id=txn.transaction_id,
        fraud_probability=round(fraud_prob, 4),
        decision="BLOCK" if fraud_prob >= 0.5 else "ALLOW",
    )
