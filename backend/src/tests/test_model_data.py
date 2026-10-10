"""Model-input validation using stored-row fixtures, never external sources."""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from database.model_data import ModelDataError, dataset_metadata, load_daily_prices

CUTOFF = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)


def repository(rows):
    return SimpleNamespace(get_model_price_rows=lambda *args, **kwargs: rows)


def test_loader_converts_database_decimals_and_orders_market_dates():
    rows = [
        {'bar_at': datetime(2026, 10, day, 4, tzinfo=timezone.utc),
         'close': Decimal(str(100 + day)), 'volume': Decimal('20')}
        for day in (8, 7)
    ]
    frame = load_daily_prices(repository(rows), 'TEST', cutoff=CUTOFF)
    assert list(frame.columns) == ['Close', 'Volume']
    assert frame['Close'].tolist() == [107., 108.]
    assert str(frame.index[0].date()) == '2026-10-07'
    assert str(frame.index.tz) == 'America/New_York'
    metadata = dataset_metadata(frame, cutoff=CUTOFF)
    assert metadata['source'] == 'postgresql' and metadata['rows'] == 2
    assert len(metadata['sha256']) == 64


@pytest.mark.parametrize('close,volume', [(None, 10), (100, None), (0, 10),
                                        (float('inf'), 10), (100, -1)])
def test_loader_rejects_unusable_numbers(close, volume):
    row = {'bar_at': CUTOFF, 'close': close, 'volume': volume}
    with pytest.raises(ModelDataError):
        load_daily_prices(repository([row]), 'TEST', cutoff=CUTOFF)


def test_loader_rejects_duplicate_sessions():
    rows = [{'bar_at': CUTOFF, 'close': 100, 'volume': 20}] * 2
    with pytest.raises(ModelDataError, match='duplicate'):
        load_daily_prices(repository(rows), 'TEST', cutoff=CUTOFF)


def test_loader_requires_saved_data_and_aware_cutoff():
    with pytest.raises(ModelDataError, match='No saved'):
        load_daily_prices(repository([]), 'TEST', cutoff=CUTOFF)
    with pytest.raises(ModelDataError, match='timezone'):
        load_daily_prices(repository([]), 'TEST', cutoff=datetime(2026, 10, 9))
