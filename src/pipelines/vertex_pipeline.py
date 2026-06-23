"""
Vertex AI Pipeline — FraudGuard end-to-end MLOps pipeline.
Runs: data-validation → train → evaluate → register → deploy-to-cloud-run

Trigger:
  python src/pipelines/vertex_pipeline.py --project vizualflo-openclaw-prod --region us-central1

Requires:
  pip install google-cloud-aiplatform kfp
"""

import argparse
import os
from typing import NamedTuple

from google.cloud import aiplatform
from kfp import compiler, dsl
from kfp.dsl import Dataset, Input, Metrics, Model, Output, component

GCS_BUCKET = "vizualflo-openclaw-prod-fraudguard-data"
AR_REPO = "us-central1-docker.pkg.dev/vizualflo-openclaw-prod/fraudguard"
PIPELINE_ROOT = f"gs://{GCS_BUCKET}/pipelines"
BASE_IMAGE = "python:3.11-slim"


@component(base_image=BASE_IMAGE, packages_to_install=["pandas", "numpy", "google-cloud-storage"])
def validate_data(
    gcs_data_path: str,
    output_dataset: Output[Dataset],
):
    """Download and validate training data from GCS."""
    import pandas as pd
    from google.cloud import storage

    bucket_name, blob_name = gcs_data_path.replace("gs://", "").split("/", 1)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.download_to_filename(output_dataset.path + ".csv")

    df = pd.read_csv(output_dataset.path + ".csv")
    assert "label" in df.columns, "label column missing"
    assert df["label"].isin([0, 1]).all(), "label must be binary"
    assert len(df) > 10_000, f"dataset too small: {len(df)} rows"

    fraud_rate = df["label"].mean()
    assert 0.001 < fraud_rate < 0.2, f"unexpected fraud rate: {fraud_rate:.2%}"

    import shutil
    shutil.copy(output_dataset.path + ".csv", output_dataset.path)
    print(f"Data validated: {len(df):,} rows, fraud rate {fraud_rate:.2%}")


@component(
    base_image=BASE_IMAGE,
    packages_to_install=["xgboost", "scikit-learn", "mlflow", "pandas", "numpy"],
)
def train_model(
    dataset: Input[Dataset],
    mlflow_tracking_uri: str,
    model: Output[Model],
    metrics: Output[Metrics],
):
    """Train XGBoost fraud model and log to MLflow."""
    import mlflow
    import mlflow.xgboost
    import pandas as pd
    import xgboost as xgb
    from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
    from sklearn.model_selection import train_test_split

    FEATURE_COLS = [
        "amount", "hour_of_day", "day_of_week", "merchant_category",
        "distance_from_home_km", "velocity_1h", "velocity_24h",
        "avg_spend_7d", "is_international", "card_present",
    ]

    df = pd.read_csv(dataset.path)
    X, y = df[FEATURE_COLS], df["label"]
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

    spw = float((y == 0).sum() / (y == 1).sum())
    clf = xgb.XGBClassifier(
        n_estimators=400, max_depth=6, learning_rate=0.05,
        scale_pos_weight=spw, eval_metric="aucpr", random_state=42,
    )
    clf.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=100)

    y_prob = clf.predict_proba(X_val)[:, 1]
    pr_auc = average_precision_score(y_val, y_prob)
    roc_auc = roc_auc_score(y_val, y_prob)
    f1 = f1_score(y_val, (y_prob >= 0.5).astype(int))

    metrics.log_metric("val_pr_auc", pr_auc)
    metrics.log_metric("val_roc_auc", roc_auc)
    metrics.log_metric("val_f1", f1)

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    with mlflow.start_run(run_name="vertex-retrain"):
        mlflow.log_metrics({"val_pr_auc": pr_auc, "val_roc_auc": roc_auc, "val_f1": f1})
        mlflow.xgboost.log_model(clf, name="model", registered_model_name="fraudguard-xgboost")

    clf.save_model(model.path + ".json")
    print(f"Training complete | PR-AUC: {pr_auc:.4f} | F1: {f1:.4f}")


@component(base_image=BASE_IMAGE, packages_to_install=["mlflow"])
def promote_model(
    mlflow_tracking_uri: str,
    model_name: str,
    min_pr_auc: float,
    metrics: Input[Metrics],
):
    """Promote model to production alias if PR-AUC meets threshold."""
    import mlflow
    from mlflow.tracking import MlflowClient

    pr_auc = metrics.metadata.get("val_pr_auc", 0)
    if pr_auc < min_pr_auc:
        raise ValueError(f"PR-AUC {pr_auc:.4f} below threshold {min_pr_auc} — not promoting")

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{model_name}'")
    latest = max(versions, key=lambda v: int(v.version))
    client.set_registered_model_alias(model_name, "production", latest.version)
    print(f"Promoted {model_name} v{latest.version} to production (PR-AUC: {pr_auc:.4f})")


@component(
    base_image=BASE_IMAGE,
    packages_to_install=["google-cloud-run", "google-cloud-aiplatform"],
)
def deploy_cloud_run(
    project: str,
    region: str,
    image_uri: str,
    service_name: str = "fraudguard-serve",
):
    """Deploy updated serving image to Cloud Run."""
    import subprocess
    cmd = [
        "gcloud", "run", "deploy", service_name,
        "--image", image_uri,
        "--region", region,
        "--project", project,
        "--platform", "managed",
        "--allow-unauthenticated",
        "--memory", "1Gi",
        "--cpu", "1",
        "--concurrency", "80",
        "--set-env-vars", "MODEL_NAME=fraudguard-xgboost,MODEL_STAGE=production",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Cloud Run deploy failed: {result.stderr}")
    print(f"Cloud Run service deployed: {result.stdout}")


@dsl.pipeline(
    name="fraudguard-mlops-pipeline",
    description="FraudGuard: validate → train → promote → deploy",
)
def fraudguard_pipeline(
    gcs_data_path: str = f"gs://{GCS_BUCKET}/data/transactions.csv",
    mlflow_tracking_uri: str = "http://mlflow-service:5000",
    model_name: str = "fraudguard-xgboost",
    min_pr_auc: float = 0.85,
    project: str = "vizualflo-openclaw-prod",
    region: str = "us-central1",
    image_uri: str = f"{AR_REPO}/fraudguard-serve:latest",
):
    validate_task = validate_data(gcs_data_path=gcs_data_path)

    train_task = train_model(
        dataset=validate_task.outputs["output_dataset"],
        mlflow_tracking_uri=mlflow_tracking_uri,
    )

    promote_task = promote_model(
        mlflow_tracking_uri=mlflow_tracking_uri,
        model_name=model_name,
        min_pr_auc=min_pr_auc,
        metrics=train_task.outputs["metrics"],
    )
    promote_task.after(train_task)

    deploy_task = deploy_cloud_run(
        project=project,
        region=region,
        image_uri=image_uri,
    )
    deploy_task.after(promote_task)


def run_pipeline(project: str, region: str, service_account: str = None):
    """Compile and submit the pipeline to Vertex AI."""
    pipeline_file = "/tmp/fraudguard_pipeline.json"
    compiler.Compiler().compile(pipeline_func=fraudguard_pipeline, package_path=pipeline_file)
    print(f"Pipeline compiled to {pipeline_file}")

    aiplatform.init(project=project, location=region)

    job = aiplatform.PipelineJob(
        display_name="fraudguard-mlops",
        template_path=pipeline_file,
        pipeline_root=PIPELINE_ROOT,
        parameter_values={
            "project": project,
            "region": region,
        },
    )

    job.submit(service_account=service_account)
    print(f"Pipeline submitted: {job.resource_name}")
    print(f"View at: https://console.cloud.google.com/vertex-ai/pipelines?project={project}")
    return job


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="vizualflo-openclaw-prod")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--service-account", default=None)
    args = parser.parse_args()
    run_pipeline(args.project, args.region, args.service_account)
