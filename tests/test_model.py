"""Unit tests for training logic — runs without MLflow server."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.train.train import FEATURE_COLS, TARGET_COL, compute_scale_pos_weight
from src.train.generate_data import generate


def test_generate_data_shape():
    df = generate(n_samples=1000, fraud_rate=0.01)
    assert len(df) == 1000
    assert TARGET_COL in df.columns
    for col in FEATURE_COLS:
        assert col in df.columns


def test_fraud_rate():
    df = generate(n_samples=10000, fraud_rate=0.02)
    actual_rate = df[TARGET_COL].mean()
    assert abs(actual_rate - 0.02) < 0.005


def test_scale_pos_weight():
    y = pd.Series([0] * 990 + [1] * 10)
    spw = compute_scale_pos_weight(y)
    assert abs(spw - 99.0) < 1.0


def test_no_nulls():
    df = generate(n_samples=5000)
    assert df[FEATURE_COLS].isnull().sum().sum() == 0


def test_feature_ranges():
    df = generate(n_samples=5000)
    assert (df["hour_of_day"].between(0, 23)).all()
    assert (df["day_of_week"].between(0, 6)).all()
    assert (df["amount"] > 0).all()
    assert df["is_international"].isin([0, 1]).all()
    assert df["card_present"].isin([0, 1]).all()
