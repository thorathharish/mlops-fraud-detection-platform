"""
XGBoost fraud model training with MLflow tracking.
Handles class imbalance via scale_pos_weight.
Logs: params, PR-AUC, ROC-AUC, F1; registers best model in MLflow Registry.
"""

import argparse
import os

import mlflow
import mlflow.xgboost
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

FEATURE_COLS = [
    "amount",
    "hour_of_day",
    "day_of_week",
    "merchant_category",
    "distance_from_home_km",
    "velocity_1h",
    "velocity_24h",
    "avg_spend_7d",
    "is_international",
    "card_present",
]
TARGET_COL = "label"
MODEL_NAME = "fraudguard-xgboost"


def load_data(path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(path)
    X = df[FEATURE_COLS]
    y = df[TARGET_COL]
    return X, y


def compute_scale_pos_weight(y: pd.Series) -> float:
    """Ratio of negatives to positives — tells XGBoost to penalise missing fraud more."""
    neg = (y == 0).sum()
    pos = (y == 1).sum()
    return float(neg / pos)


def train(data_path: str, test_path: str, run_name: str = "fraudguard-train") -> str:
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    mlflow.set_experiment("fraudguard")

    X, y = load_data(data_path)
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

    X_test, y_test = load_data(test_path)

    spw = compute_scale_pos_weight(y_train)

    params = {
        "n_estimators": 400,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "scale_pos_weight": spw,
        "eval_metric": "aucpr",
        "use_label_encoder": False,
        "random_state": 42,
        "n_jobs": -1,
    }

    with mlflow.start_run(run_name=run_name) as run:
        mlflow.log_params(params)
        mlflow.log_param("train_rows", len(X_train))
        mlflow.log_param("val_rows", len(X_val))
        mlflow.log_param("fraud_rate_train", float(y_train.mean()))

        model = xgb.XGBClassifier(**params)
        model.fit(
            X_train, y_train,
            eval_set=[(X_val, y_val)],
            verbose=50,
        )

        # Validation metrics
        y_prob_val = model.predict_proba(X_val)[:, 1]
        y_pred_val = (y_prob_val >= 0.5).astype(int)
        pr_auc_val = average_precision_score(y_val, y_prob_val)
        roc_auc_val = roc_auc_score(y_val, y_prob_val)
        f1_val = f1_score(y_val, y_pred_val)

        # Test metrics
        y_prob_test = model.predict_proba(X_test)[:, 1]
        y_pred_test = (y_prob_test >= 0.5).astype(int)
        pr_auc_test = average_precision_score(y_test, y_prob_test)
        roc_auc_test = roc_auc_score(y_test, y_prob_test)
        f1_test = f1_score(y_test, y_pred_test)

        mlflow.log_metrics({
            "val_pr_auc": pr_auc_val,
            "val_roc_auc": roc_auc_val,
            "val_f1": f1_val,
            "test_pr_auc": pr_auc_test,
            "test_roc_auc": roc_auc_test,
            "test_f1": f1_test,
        })

        print("\n=== Validation ===")
        print(f"  PR-AUC : {pr_auc_val:.4f}")
        print(f"  ROC-AUC: {roc_auc_val:.4f}")
        print(f"  F1     : {f1_val:.4f}")
        print("\n=== Test ===")
        print(f"  PR-AUC : {pr_auc_test:.4f}")
        print(f"  ROC-AUC: {roc_auc_test:.4f}")
        print(f"  F1     : {f1_test:.4f}")
        print(classification_report(y_test, y_pred_test, target_names=["legit", "fraud"]))

        # Log feature importance
        importance = dict(zip(FEATURE_COLS, model.feature_importances_.tolist()))
        mlflow.log_dict(importance, "feature_importance.json")

        # Log and register model
        mlflow.xgboost.log_model(
            model,
            artifact_path="model",
            registered_model_name=MODEL_NAME,
            input_example=X_val.iloc[:5],
        )

        run_id = run.info.run_id
        print(f"\nMLflow run_id: {run_id}")
        return run_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data/raw/transactions.csv")
    parser.add_argument("--test-data", default="data/raw/transactions_test.csv")
    parser.add_argument("--run-name", default="fraudguard-train")
    args = parser.parse_args()
    train(args.data, args.test_data, args.run_name)
