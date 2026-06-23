"""Integration tests for the FastAPI serving endpoint (MLflow mocked)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

SAMPLE_TXN = {
    "transaction_id": "txn_test_001",
    "amount": 250.0,
    "hour_of_day": 14,
    "day_of_week": 2,
    "merchant_category": 5,
    "distance_from_home_km": 12.0,
    "velocity_1h": 1,
    "velocity_24h": 5,
    "avg_spend_7d": 180.0,
    "is_international": 0,
    "card_present": 1,
}

FRAUD_TXN = {
    **SAMPLE_TXN,
    "transaction_id": "txn_fraud_001",
    "amount": 9999.0,
    "velocity_1h": 8,
    "is_international": 1,
}


def _make_mock_model(fraud_prob: float = 0.15):
    m = MagicMock()
    m.predict_proba.return_value = np.array([[1 - fraud_prob, fraud_prob]])
    return m


@pytest.fixture
def client():
    mock_model = _make_mock_model(0.15)
    # Patch mlflow.xgboost.load_model so the lifespan doesn't hit a real server
    with patch("mlflow.xgboost.load_model", return_value=mock_model):
        from src.serve.app import app
        with TestClient(app) as c:
            yield c, mock_model


def test_health(client):
    c, _ = client
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["model_loaded"] is True


def test_predict_allow(client):
    c, mock_model = client
    mock_model.predict_proba.return_value = np.array([[0.9, 0.1]])
    r = c.post("/predict", json=SAMPLE_TXN)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "ALLOW"
    assert 0.0 <= data["fraud_probability"] <= 1.0
    assert data["latency_ms"] > 0


def test_predict_block(client):
    c, mock_model = client
    mock_model.predict_proba.return_value = np.array([[0.1, 0.9]])
    r = c.post("/predict", json=FRAUD_TXN)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"] == "BLOCK"
    assert data["fraud_probability"] >= 0.5


def test_metrics_endpoint(client):
    c, mock_model = client
    mock_model.predict_proba.return_value = np.array([[0.8, 0.2]])
    c.post("/predict", json=SAMPLE_TXN)  # generate at least one metric
    r = c.get("/metrics")
    assert r.status_code == 200
    assert b"fraudguard_requests_total" in r.content


def test_invalid_payload(client):
    c, _ = client
    r = c.post("/predict", json={"amount": -1})
    assert r.status_code == 422
