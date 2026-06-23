"""
End-to-end inference demo:
  1. Pull pre-computed features from Feast online store (Redis)
  2. Call the FastAPI /predict endpoint
  3. Print result

Run after: feast materialize-incremental $(date +%Y-%m-%dT%H:%M:%S)
"""

import os

import requests

SERVE_URL = os.getenv("SERVE_URL", "http://localhost:8000")


def fetch_features_from_feast(transaction_id: str, feast_repo_path: str = "src/features/feature_repo") -> dict:
    """Pull online features from Redis via Feast."""
    try:
        from feast import FeatureStore
        store = FeatureStore(repo_path=feast_repo_path)
        feature_vector = store.get_online_features(
            features=[
                "transaction_features:amount",
                "transaction_features:hour_of_day",
                "transaction_features:day_of_week",
                "transaction_features:merchant_category",
                "transaction_features:distance_from_home_km",
                "transaction_features:velocity_1h",
                "transaction_features:velocity_24h",
                "transaction_features:avg_spend_7d",
                "transaction_features:is_international",
                "transaction_features:card_present",
            ],
            entity_rows=[{"transaction_id": transaction_id}],
        ).to_dict()
        return {k: v[0] for k, v in feature_vector.items() if k != "transaction_id"}
    except Exception as e:
        print(f"[WARN] Feast unavailable ({e}), using mock features")
        return None


def predict(payload: dict) -> dict:
    r = requests.post(f"{SERVE_URL}/predict", json=payload, timeout=5)
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    # Sample transaction to score
    sample = {
        "transaction_id": "txn_demo_001",
        "amount": 4500.0,
        "hour_of_day": 2,
        "day_of_week": 5,
        "merchant_category": 7,
        "distance_from_home_km": 350.0,
        "velocity_1h": 6,
        "velocity_24h": 22,
        "avg_spend_7d": 80.0,
        "is_international": 1,
        "card_present": 0,
    }

    # Try to enrich from Feast first
    feast_features = fetch_features_from_feast(sample["transaction_id"])
    if feast_features:
        sample.update(feast_features)
        print("Features loaded from Feast/Redis online store")
    else:
        print("Using hardcoded sample features (Feast not materialised)")

    result = predict(sample)
    print(f"\nTransaction : {result['transaction_id']}")
    print(f"Fraud score : {result['fraud_probability']:.4f}")
    print(f"Decision    : {result['decision']}")
    print(f"Latency     : {result['latency_ms']:.2f} ms")
