# How stored prices reach the model

The loader is the adapter between PostgreSQL rows and the numerical model.

```
Online refresh -> save price_bars -> read saved daily rows
-> validate and convert to pandas -> regression features -> forecast
```

`database/model_data.py` returns a table with `Close` and `Volume`, ordered by
market date. It uses daily yfinance data with one consistent adjustment basis.
It reads the full requested history, rather than the dashboard's capped result.

The loader rejects missing/non-finite numbers, non-positive prices, negative
volumes, and duplicate daily sessions. It does not invent missing values. The
regression checks that enough usable history remains after building features.

Each database-backed forecast also freezes its exact Close/Volume rows in the
immutable `model_datasets` table (`database/datasets.py`). The forecast's
`input_snapshot.regression_dataset` records the `dataset_id`, row count, date
range, cutoff, and sha256, so a past regression can be replayed exactly with
`DatasetStore(connection).load(dataset_id)` even after later price corrections.

Price refreshes update corrected values in `price_bars` only when their fetch is
at least as new as the saved record. That table is the latest view, not history.

## What works offline?

The standalone loader plus `run_regression` can use saved data without an online
fetch or a Gemini call. The full agent forecast still refreshes market/company
information first; this change does not provide an offline persona mode.

## Later neural network

Reuse this validated input table. Add a separate feature/sequence builder,
chronological training/validation split, and model artifact management. For
example, turn a window of past returns/volume into inputs and the next five
returns into targets. The loader does not itself train a neural network.
