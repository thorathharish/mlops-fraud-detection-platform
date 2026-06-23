"""
Feast feature definitions for FraudGuard.
Defines: entity (transaction), feature view (transaction_features), on-demand features.
"""

from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, Int32

transaction = Entity(name="transaction_id", description="Unique transaction identifier")

transaction_source = FileSource(
    path=str(Path("data/raw/transactions.csv").resolve()),
    timestamp_field="timestamp",
)

transaction_features = FeatureView(
    name="transaction_features",
    entities=[transaction],
    ttl=timedelta(hours=24),
    schema=[
        Field(name="amount", dtype=Float32),
        Field(name="hour_of_day", dtype=Int32),
        Field(name="day_of_week", dtype=Int32),
        Field(name="merchant_category", dtype=Int32),
        Field(name="distance_from_home_km", dtype=Float32),
        Field(name="velocity_1h", dtype=Int32),
        Field(name="velocity_24h", dtype=Int32),
        Field(name="avg_spend_7d", dtype=Float32),
        Field(name="is_international", dtype=Int32),
        Field(name="card_present", dtype=Int32),
    ],
    source=transaction_source,
    tags={"team": "fraud", "model": "fraudguard-xgboost"},
)
