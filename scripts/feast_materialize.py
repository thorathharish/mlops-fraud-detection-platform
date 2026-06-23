"""
Materialize Feast features into Redis online store.
Run once after training data is generated, then on a schedule (e.g. hourly).
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Feast repo is relative to project root
REPO_PATH = str(Path(__file__).parent.parent / "src" / "features" / "feature_repo")


def apply_and_materialize():
    from feast import FeatureStore

    store = FeatureStore(repo_path=REPO_PATH)

    print("Applying feature store registry...")
    store.apply([])  # picks up objects from features.py automatically via repo scan

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=30)

    print(f"Materializing features {start_date.date()} -> {end_date.date()} into Redis...")
    store.materialize(start_date=start_date, end_date=end_date)
    print("Materialization complete. Redis online store is ready.")


if __name__ == "__main__":
    apply_and_materialize()
