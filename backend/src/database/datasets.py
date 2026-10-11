"""Immutable numerical datasets, captured from a forecast's exact market snapshot."""
from __future__ import annotations

import json
from hashlib import sha256
from uuid import uuid4

import pandas as pd

from database.model_data import ModelDataError, daily_prices_from_rows, dataset_metadata


def dataset_rows(frame):
    return [{"bar_at": timestamp.isoformat(), "close": float(row.Close),
             "volume": float(row.Volume)} for timestamp, row in frame.iterrows()]


def fingerprint(rows):
    return sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


class DatasetStore:
    def __init__(self, connection):
        self.connection = connection

    def capture(self, ticker, daily, *, fetched_at, cutoff):
        """Copy, validate, and persist values supplied to this forecast, never latest bars."""
        if fetched_at.tzinfo is None or cutoff.tzinfo is None:
            raise ModelDataError("Model dataset bounds must include a timezone.")
        if fetched_at > cutoff:
            raise ModelDataError("Model snapshot was fetched after the forecast cutoff.")
        rows = []
        for timestamp, row in daily.copy(deep=True).iterrows():
            timestamp = pd.Timestamp(timestamp)
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("America/New_York")
            close = row.get("Close")
            # Same rule as price_bars ingestion: a provider row without a close
            # (e.g. an unfinished session) is not a bar. Other gaps still fail.
            if close is None or pd.isna(close):
                continue
            rows.append({"bar_at": timestamp, "close": close, "volume": row.get("Volume")})
        frame = daily_prices_from_rows(rows)
        payload = dataset_rows(frame)
        dataset_id = str(uuid4())
        metadata = dataset_metadata(frame, cutoff=cutoff)
        metadata.update(dataset_id=dataset_id, table="model_datasets", ticker=ticker,
                        fetched_at=fetched_at.isoformat(), sha256=fingerprint(payload),
                        capture_basis="exact fetched market snapshot")
        from psycopg.types.json import Jsonb
        self.connection.execute(
            "INSERT INTO model_datasets (id, ticker, fetched_at, cutoff_at, metadata, price_rows) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (dataset_id, ticker, fetched_at, cutoff, Jsonb(metadata), Jsonb(payload)))
        return dataset_id

    def load(self, dataset_id):
        """Replay saved rows even after corrections or concurrent refreshes of price_bars."""
        row = self.connection.execute(
            "SELECT metadata, price_rows FROM model_datasets WHERE id = %s", (dataset_id,)).fetchone()
        if row is None:
            raise ModelDataError("Saved model dataset not found.")
        metadata = row["metadata"]
        if metadata["sha256"] != fingerprint(row["price_rows"]):
            raise ModelDataError("Saved model dataset fingerprint does not match its rows.")
        frame = daily_prices_from_rows(row["price_rows"])
        frame.attrs["regression_dataset"] = dict(metadata)
        return frame
