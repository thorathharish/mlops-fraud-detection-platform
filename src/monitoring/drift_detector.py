"""
Drift detection using Evidently.
Compares live inference data against the training reference snapshot.
Outputs a drift report (HTML + JSON) and returns a boolean: drift_detected.
"""

import json
from pathlib import Path

import pandas as pd
from evidently.legacy.metric_preset import DataDriftPreset
from evidently.legacy.pipeline.column_mapping import ColumnMapping
from evidently.legacy.report import Report

FEATURE_COLS = [
    "amount", "hour_of_day", "day_of_week", "merchant_category",
    "distance_from_home_km", "velocity_1h", "velocity_24h",
    "avg_spend_7d", "is_international", "card_present",
]
DRIFT_THRESHOLD = 0.3  # fraction of drifted features that triggers alert


def detect_drift(
    reference_path: str = "data/reference/reference.csv",
    current_path: str = "data/raw/transactions_drifted.csv",
    report_dir: str = "reports",
) -> dict:
    Path(report_dir).mkdir(parents=True, exist_ok=True)

    reference = pd.read_csv(reference_path)[FEATURE_COLS]
    current = pd.read_csv(current_path)[FEATURE_COLS]

    column_mapping = ColumnMapping(numerical_features=FEATURE_COLS)

    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=reference, current_data=current, column_mapping=column_mapping)

    report.save_html(f"{report_dir}/drift_report.html")

    result = report.as_dict()
    # metrics[0] = dataset-level summary (share_of_drifted_columns, dataset_drift)
    # metrics[1] = per-column breakdown with drift_by_columns
    column_details = result["metrics"][1]["result"]

    n_drifted = column_details["number_of_drifted_columns"]
    n_total = column_details["number_of_columns"]
    drift_fraction = n_drifted / n_total
    drift_detected = drift_fraction >= DRIFT_THRESHOLD

    drifted_features = [
        col for col, v in column_details.get("drift_by_columns", {}).items()
        if v.get("drift_detected")
    ]

    summary = {
        "drift_detected": drift_detected,
        "drift_fraction": round(drift_fraction, 4),
        "n_drifted_features": n_drifted,
        "n_total_features": n_total,
        "threshold": DRIFT_THRESHOLD,
        "dataset_drift": column_details.get("dataset_drift", False),
        "drifted_features": drifted_features,
    }

    with open(f"{report_dir}/drift_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Drift detected: {drift_detected}")
    print(f"Drifted {n_drifted}/{n_total} features ({drift_fraction:.1%})")
    print(f"Drifted features: {drifted_features}")

    return summary


if __name__ == "__main__":
    summary = detect_drift()
    if summary["drift_detected"]:
        print("\nACTION REQUIRED: Drift threshold exceeded - trigger retrain pipeline.")
        exit(1)  # non-zero exit triggers GitHub Actions retrain job
    else:
        print("\nNo significant drift detected.")
        exit(0)
