"""
Generates a synthetic fraud detection dataset (~100k transactions, ~1% fraud rate).
Saves to data/raw/transactions.csv and data/reference/reference.csv (training baseline for drift detection).
"""

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_SAMPLES = 100_000
FRAUD_RATE = 0.01


def generate(n_samples: int = N_SAMPLES, fraud_rate: float = FRAUD_RATE, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n_fraud = int(n_samples * fraud_rate)
    n_legit = n_samples - n_fraud

    def legit_records(n):
        return {
            "amount": rng.lognormal(mean=3.5, sigma=1.2, size=n),
            "hour_of_day": rng.integers(0, 24, size=n),
            "day_of_week": rng.integers(0, 7, size=n),
            "merchant_category": rng.integers(0, 20, size=n),
            "distance_from_home_km": rng.exponential(scale=15, size=n),
            "velocity_1h": rng.poisson(lam=1.5, size=n),
            "velocity_24h": rng.poisson(lam=8, size=n),
            "avg_spend_7d": rng.lognormal(mean=3.0, sigma=1.0, size=n),
            "is_international": rng.choice([0, 1], p=[0.88, 0.12], size=n),
            "card_present": rng.choice([0, 1], p=[0.25, 0.75], size=n),
            "label": np.zeros(n, dtype=int),
        }

    def fraud_records(n):
        return {
            "amount": rng.lognormal(mean=5.5, sigma=1.5, size=n),
            "hour_of_day": rng.choice([0, 1, 2, 3, 22, 23], size=n),
            "day_of_week": rng.integers(0, 7, size=n),
            "merchant_category": rng.integers(0, 20, size=n),
            "distance_from_home_km": rng.exponential(scale=80, size=n),
            "velocity_1h": rng.poisson(lam=5, size=n),
            "velocity_24h": rng.poisson(lam=20, size=n),
            "avg_spend_7d": rng.lognormal(mean=2.5, sigma=1.2, size=n),
            "is_international": rng.choice([0, 1], p=[0.4, 0.6], size=n),
            "card_present": rng.choice([0, 1], p=[0.7, 0.3], size=n),
            "label": np.ones(n, dtype=int),
        }

    df = pd.concat(
        [pd.DataFrame(legit_records(n_legit)), pd.DataFrame(fraud_records(n_fraud))],
        ignore_index=True,
    ).sample(frac=1, random_state=seed).reset_index(drop=True)

    df["transaction_id"] = [f"txn_{i:07d}" for i in range(len(df))]
    df["timestamp"] = pd.date_range("2024-01-01", periods=len(df), freq="1min")
    return df


def generate_drifted(base_df: pd.DataFrame, seed: int = 99) -> pd.DataFrame:
    """
    Simulates a realistic population-level distribution shift:
    - Amount inflation (e.g. holiday season, inflation)
    - Velocity spike across all customers
    - Shift toward evening/night transactions
    - More international transactions
    This affects the whole population, not just fraud records, making it detectable.
    """
    rng = np.random.default_rng(seed)
    df = base_df.copy()

    # Whole-population shifts
    df["amount"] = df["amount"] * rng.uniform(2.0, 4.0, size=len(df))
    df["velocity_1h"] = (df["velocity_1h"] * rng.uniform(2.5, 4.0, size=len(df))).astype(int)
    df["velocity_24h"] = (df["velocity_24h"] * rng.uniform(2.0, 3.5, size=len(df))).astype(int)
    df["hour_of_day"] = rng.integers(18, 24, size=len(df))  # night-time shift
    df["distance_from_home_km"] = df["distance_from_home_km"] * rng.uniform(3.0, 6.0, size=len(df))
    df["is_international"] = rng.choice([0, 1], p=[0.35, 0.65], size=len(df))  # more intl

    return df


if __name__ == "__main__":
    out_raw = Path("data/raw")
    out_ref = Path("data/reference")
    out_raw.mkdir(parents=True, exist_ok=True)
    out_ref.mkdir(parents=True, exist_ok=True)

    df = generate()
    split = int(len(df) * 0.8)
    df.iloc[:split].to_csv(out_raw / "transactions.csv", index=False)
    df.iloc[split:].to_csv(out_raw / "transactions_test.csv", index=False)

    # Reference snapshot used by Evidently for drift baseline
    df.iloc[:5000].to_csv(out_ref / "reference.csv", index=False)

    drifted = generate_drifted(df)
    drifted.to_csv(out_raw / "transactions_drifted.csv", index=False)

    print(f"Generated {len(df):,} rows  |  fraud rate: {df['label'].mean():.2%}")
    print("Saved train -> data/raw/transactions.csv")
    print("Saved test  -> data/raw/transactions_test.csv")
    print("Saved drift -> data/raw/transactions_drifted.csv")
    print("Saved ref   -> data/reference/reference.csv")
