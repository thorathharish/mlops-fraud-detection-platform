"""
Promote the latest MLflow model version to a given stage (e.g. Staging → Production).
Called by the retrain GitHub Actions workflow after a successful training run.
"""

import argparse
import os
import mlflow
from mlflow.tracking import MlflowClient


def promote(model_name: str, stage: str) -> None:
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    client = MlflowClient()

    versions = client.search_model_versions(f"name='{model_name}'")
    if not versions:
        raise RuntimeError(f"No versions found for model '{model_name}'")

    latest = max(versions, key=lambda v: int(v.version))
    print(f"Promoting {model_name} v{latest.version} -> alias '{stage}'")

    # MLflow 3.x uses aliases instead of stages
    alias = stage.lower()  # e.g. "Production" → "production"
    client.set_registered_model_alias(model_name, alias, latest.version)
    print(f"Done. {model_name} v{latest.version} aliased as '{alias}'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", default="fraudguard-xgboost")
    parser.add_argument("--stage", default="Production")
    args = parser.parse_args()
    promote(args.model_name, args.stage)
