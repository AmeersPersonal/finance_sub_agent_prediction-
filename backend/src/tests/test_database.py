"""Synthetic persistence checks; integration uses an opt-in local Unix socket only."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pandas as pd
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from ai.evaluation import score
from ai.main import predict
from database.connection import DatabaseError, connect
from database.migrate import migrate
from database.repository import DatabaseRepository

CORE_MIGRATIONS = [
    "001_initial.sql",
    "003_dataset.sql",
    "004_evaluations_immutable.sql",
]


def test_missing_configuration_is_safe(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DatabaseError, match="Set DATABASE_URL"):
        with connect():
            pytest.fail("Should not connect")


def test_bad_configuration_does_not_expose_credentials():
    with pytest.raises(DatabaseError) as error:
        with connect("password=PRIVATE_TEST_SECRET malformed"):
            pytest.fail("Should not connect")
    assert "PRIVATE_TEST_SECRET" not in str(error.value)


def test_inputs_are_frozen_without_private_document_text(snapshot, fake_llm, monkeypatch):
    from ai.rag_retrieval import Snippet

    monkeypatch.setattr("ai.main.strategy_documents", lambda *_: [Snippet("test.md", "PRIVATE_SOURCE_TEXT")])
    prediction = asyncio.run(predict("TEST", snapshot=snapshot, llm=fake_llm))
    assert prediction.input_snapshot["strategy_packets"]["day_trader"]["ticker"] == "TEST"
    assert len(prediction.input_snapshot["selected_age_bands"]) == 5
    assert "PRIVATE_SOURCE_TEXT" not in prediction.model_dump_json()
    assert prediction.input_snapshot["document_references"]["long_term"] == ["test.md"]


@pytest.fixture
def db():
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set TEST_DATABASE_URL to an isolated local PostgreSQL Unix socket")
    options = conninfo_to_dict(dsn)
    if not options.get("host", "").startswith("/"):
        pytest.fail("Database tests permit local Unix sockets only; never cloud connections")
    schema = "test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        try:
            assert migrate(connection) == CORE_MIGRATIONS
            yield connection
        finally:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_migration_is_repeatable(db):
    assert migrate(db) == []
    assert db.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] == len(CORE_MIGRATIONS)


def test_prediction_roundtrip_idempotency_and_immutability(db, snapshot, failing_llm):
    p = asyncio.run(predict("TEST", snapshot=snapshot, llm=failing_llm))
    repo = DatabaseRepository(db)
    assert repo.save_prediction(p)
    assert not repo.save_prediction(p)
    assert repo.get_prediction(p.id) == p
    assert repo.load_predictions(ticker="test") == [p]
    assert db.execute("SELECT count(*) AS n FROM prediction_outputs WHERE run_id = %s", (p.id,)).fetchone()["n"] == 18
    with pytest.raises(DatabaseError, match="different contents"):
        repo.save_prediction(p.model_copy(update={"direction": "down"}))
    with pytest.raises(psycopg.Error):
        db.execute("UPDATE prediction_runs SET last_price = 1 WHERE id = %s", (p.id,))
    assert repo.get_prediction(p.id) == p


def test_source_versions_and_price_bases(db):
    repo = DatabaseRepository(db)
    kwargs = dict(source_url="https://example.com/news", title="Synthetic news",
                  document_type="news", symbols=["TEST"],
                  first_seen_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    first = repo.store_document(content_text="First version", **kwargs)
    assert repo.store_document(content_text="First version", **kwargs) == first
    second = repo.store_document(content_text="Revised version", **kwargs)
    assert first != second
    bars = [{"bar_at": datetime(2026, 10, 1, tzinfo=timezone.utc), "close": 100, "volume": 10}]
    assert repo.save_price_bars("TEST", bars, interval="1d") == 1
    assert repo.save_price_bars("TEST", bars, interval="1d") == 0
    assert repo.save_price_bars("TEST", bars, interval="1d", adjustment_basis="total_return") == 1


def test_future_evidence_is_rejected(db, snapshot, fake_llm):
    p = asyncio.run(predict("TEST", snapshot=snapshot, llm=fake_llm))
    repo = DatabaseRepository(db)
    repo.save_prediction(p)
    future = repo.store_document(source_url="https://example.com/future", title="Future",
                                 content_text="Not available yet", document_type="news",
                                 first_seen_at=p.generated_at + timedelta(days=1))
    statement = """INSERT INTO prediction_evidence
        (run_id, document_id, evidence_role, excerpt_text, retrieved_at)
        VALUES (%s, %s, 'company_info', 'Synthetic excerpt', %s)"""
    with pytest.raises(psycopg.Error, match="not available"):
        db.execute(statement, (p.id, future, p.generated_at))
    current = repo.store_document(source_url="https://example.com/current", title="Current",
                                  content_text="Available evidence", document_type="news",
                                  first_seen_at=p.generated_at - timedelta(minutes=1))
    db.execute(statement, (p.id, current, p.generated_at))
    assert db.execute("SELECT count(*) AS n FROM prediction_evidence").fetchone()["n"] == 1


def test_evaluation_preserves_forecast_and_exact_price(db, snapshot, fake_llm):
    p = asyncio.run(predict("TEST", snapshot=snapshot, llm=fake_llm))
    repo = DatabaseRepository(db)
    repo.save_prediction(p)
    closes = pd.Series([p.last_price] + [p.last_price * 1.037123] * 5,
                       index=[d.date() for d in pd.bdate_range(p.data_as_of, periods=6)])
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    report = score([p], {"TEST": closes}, now)
    assert repo.save_evaluations(report, evaluated_at=now) == 18
    assert repo.save_evaluations(report, evaluated_at=now) == 0
    row = db.execute("SELECT actual_price, payload FROM evaluations LIMIT 1").fetchone()
    assert float(row["actual_price"]) == pytest.approx(closes.iloc[-1])
    assert not row["payload"]["price_is_derived"]
    assert repo.get_prediction(p.id) == p


def test_invalid_output_rolls_back_whole_run(db, snapshot, fake_llm):
    p = asyncio.run(predict("TEST", snapshot=snapshot, llm=fake_llm))
    p.personas[0].strategy = "invalid"
    repo = DatabaseRepository(db)
    with pytest.raises(DatabaseError):
        repo.save_prediction(p)
    assert repo.get_prediction(p.id) is None
    assert db.execute("SELECT count(*) AS n FROM instruments").fetchone()["n"] == 0


def test_retrieval_uses_latest_available_version_and_excludes_future(db):
    repo = DatabaseRepository(db)
    cutoff = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    kwargs = dict(source_url="https://example.com/revenue", title="Revenue",
                  document_type="news", content_kind="excerpt", symbols=["TEST"])
    old = repo.store_document(content_text="Old revenue outlook", first_seen_at=cutoff - timedelta(days=2), **kwargs)
    new = repo.store_document(content_text="New revenue outlook", first_seen_at=cutoff - timedelta(days=1), **kwargs)
    future = repo.store_document(content_text="Future revenue outlook", first_seen_at=cutoff + timedelta(days=1), **kwargs)
    for document_id, text in ((old, "Old revenue"), (new, "New revenue"), (future, "Future revenue")):
        repo.store_chunks(document_id, [text])
    results = repo.retrieve_passages("TEST", "revenue", cutoff=cutoff)
    assert len(results) == 1 and results[0]["document_id"] == new
    assert results[0]["text"] == "New revenue"
    assert repo.retrieve_passages("TEST", "revenue", cutoff=cutoff - timedelta(days=3)) == []


def test_dashboard_price_read_keeps_one_adjustment_basis(db):
    repo = DatabaseRepository(db)
    bars = [{"bar_at": datetime(2026, 10, day, tzinfo=timezone.utc), "close": day * 10}
            for day in (1, 2, 3)]
    repo.save_price_bars("TEST", bars, interval="1d", adjustment_basis="raw")
    repo.save_price_bars("TEST", bars, interval="1d", adjustment_basis="total_return")
    results = repo.get_price_history("TEST", limit=2)
    assert [float(row["close"]) for row in results] == [20, 30]
    assert all(row["adjustment_basis"] == "total_return" for row in results)


def test_forecast_with_evidence_saves_atomically(db, snapshot, fake_llm):
    repo = DatabaseRepository(db)
    prediction = asyncio.run(predict("TEST", snapshot=snapshot, llm=fake_llm))
    cutoff = prediction.generated_at
    document_id = repo.store_document(source_url="https://example.com/source", title="Source",
                                     content_text="Revenue growth outlook", document_type="news",
                                     first_seen_at=cutoff - timedelta(minutes=1), symbols=["TEST"],
                                     classification={"role": "company_info"})
    repo.store_chunks(document_id, ["Revenue growth outlook"])
    passage = repo.retrieve_passages("TEST", "revenue", cutoff=cutoff)[0]
    repo.save_prediction(prediction)
    repo.save_evidence(prediction.id, passage, retrieved_at=cutoff, strategy="long_term", cited_by=[])
    row = db.execute("SELECT excerpt_text, metadata FROM prediction_evidence").fetchone()
    assert row["excerpt_text"] == "Revenue growth outlook"
    assert row["metadata"]["provided_to_model"] and row["metadata"]["cited_by"] == []
    assert repo.list_documents("TEST")[0]["source_url"] == "https://example.com/source"


def test_model_dataset_has_full_history_and_point_in_time_filters(db):
    from database.model_data import load_daily_prices

    repo = DatabaseRepository(db)
    cutoff = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    dates = pd.bdate_range('2023-01-02', periods=600, tz='America/New_York')
    bars = [{'bar_at': at.to_pydatetime(), 'close': 100 + n, 'volume': 1000,
             'fetched_at': cutoff - timedelta(hours=1)} for n, at in enumerate(dates)]
    repo.save_price_bars('TEST', bars, interval='1d', adjustment_basis='total_return')
    # Different adjustment data must not enter the model's dataset.
    repo.save_price_bars('TEST', bars, interval='1d', adjustment_basis='raw')
    repo.save_price_bars('TEST', [{'bar_at': datetime(2026, 10, 9, 4, tzinfo=timezone.utc),
                                 'close': 999, 'volume': 1000,
                                 'fetched_at': cutoff + timedelta(hours=1)}],
                        interval='1d', adjustment_basis='total_return')
    daily = load_daily_prices(repo, 'TEST', cutoff=cutoff)
    assert len(daily) == 600  # unlike the chart's default 500-row limit
    assert daily['Close'].iloc[-1] == 699
    bounded = load_daily_prices(repo, 'TEST', cutoff=cutoff,
                               start_at=dates[100].to_pydatetime(), end_at=dates[199].to_pydatetime())
    assert len(bounded) == 100


def test_corrected_prices_refresh_without_older_fetch_overwriting(db):
    repo = DatabaseRepository(db)
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    first = {'bar_at': at, 'close': 100, 'volume': 1000, 'fetched_at': at}
    newer = {**first, 'close': 105, 'fetched_at': at + timedelta(hours=1)}
    assert repo.save_price_bars('TEST', [first], interval='1d', adjustment_basis='total_return') == 1
    assert repo.save_price_bars('TEST', [newer], interval='1d', adjustment_basis='total_return') == 1
    assert repo.save_price_bars('TEST', [first], interval='1d', adjustment_basis='total_return') == 0
    assert float(repo.get_price_history('TEST')[0]['close']) == 105


def test_retrieval_ranks_any_strategy_keyword_not_all_of_them(db):
    from ai.agents import DOC_QUERIES
    from ai.personas import Strategy

    repo = DatabaseRepository(db)
    cutoff = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    relevant = repo.store_document(source_url="https://example.com/guidance", title="Guidance",
                                   content_text="Revenue earnings guidance increased this quarter",
                                   document_type="news", first_seen_at=cutoff - timedelta(days=2),
                                   symbols=["TEST"])
    newer = repo.store_document(source_url="https://example.com/weather", title="Weather",
                                content_text="The office picnic was sunny", document_type="news",
                                first_seen_at=cutoff - timedelta(hours=1), symbols=["TEST"])
    repo.store_chunks(relevant, ["Revenue earnings guidance increased this quarter"])
    repo.store_chunks(newer, ["The office picnic was sunny"])
    # Previously the keyword bag was ANDed, so this scored zero and recency won.
    results = repo.retrieve_passages("TEST", DOC_QUERIES[Strategy.LONG_TERM], cutoff=cutoff)
    assert [r["document_id"] for r in results] == [relevant]
    assert results[0]["relevance"] > 0
    # Query punctuation ("S&P") is not parsed as tsquery syntax; no match -> recency fallback.
    fallback = repo.retrieve_passages("TEST", DOC_QUERIES[Strategy.INDEX_OPTIONS], cutoff=cutoff)
    assert [r["document_id"] for r in fallback] == [newer, relevant]
    assert all(r["relevance"] == 0 for r in fallback)
    assert repo.retrieve_passages("TEST", "", cutoff=cutoff)[0]["document_id"] == newer


def test_model_dataset_is_frozen_against_price_corrections(db, snapshot):
    from database.datasets import DatasetStore
    from database.model_data import ModelDataError

    repo = DatabaseRepository(db)
    store = DatasetStore(db)
    cutoff = snapshot.fetched_at + timedelta(minutes=1)
    daily = snapshot.daily.copy()
    daily.loc[daily.index[-1] + pd.Timedelta(days=3)] = [None, None, None, float("nan"), None]
    dataset_id = store.capture("TEST", daily, fetched_at=snapshot.fetched_at, cutoff=cutoff)
    # A later correction of stored bars must not change what the forecast used.
    last = snapshot.daily.index[-1].to_pydatetime()
    repo.save_price_bars("TEST", [{"bar_at": last, "close": 1.0, "volume": 1.0,
                                   "fetched_at": cutoff + timedelta(days=1)}],
                         interval="1d", adjustment_basis="total_return")
    frame = store.load(dataset_id)
    assert len(frame) == len(snapshot.daily)  # unfinished NaN-close row skipped
    assert frame["Close"].to_numpy() == pytest.approx(snapshot.daily["Close"].to_numpy())
    assert frame.attrs["regression_dataset"]["dataset_id"] == dataset_id
    with pytest.raises(psycopg.Error):
        db.execute("UPDATE model_datasets SET price_rows = '[{}]' WHERE id = %s", (dataset_id,))
    with pytest.raises(psycopg.Error):
        db.execute("DELETE FROM model_datasets WHERE id = %s", (dataset_id,))
    with pytest.raises(ModelDataError):
        store.capture("TEST", daily, fetched_at=cutoff + timedelta(seconds=1), cutoff=cutoff)


def test_evaluations_are_append_only(db, snapshot, fake_llm):
    p = asyncio.run(predict("TEST", snapshot=snapshot, llm=fake_llm))
    repo = DatabaseRepository(db)
    repo.save_prediction(p)
    closes = pd.Series([p.last_price] * 6,
                       index=[d.date() for d in pd.bdate_range(p.data_as_of, periods=6)])
    now = datetime(2026, 10, 20, tzinfo=timezone.utc)
    repo.save_evaluations(score([p], {"TEST": closes}, now), evaluated_at=now)
    row = db.execute("SELECT id, payload FROM evaluations LIMIT 1").fetchone()
    assert row["payload"]["price_basis"] == "prediction_share_basis"
    assert row["payload"]["split_factor"] == 1.0
    with pytest.raises(psycopg.Error):
        db.execute("UPDATE evaluations SET correct = NOT correct WHERE id = %s", (row["id"],))
    with pytest.raises(psycopg.Error):
        db.execute("DELETE FROM evaluations WHERE id = %s", (row["id"],))


def test_retrieval_filters_by_evidence_role(db):
    repo = DatabaseRepository(db)
    cutoff = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    ids = {}
    for role, text in [("company_info", "Revenue guidance in the press release"),
                       ("public_opinion", "Analysts debate revenue guidance"),
                       (None, "Revenue guidance from an unclassified note")]:
        ids[role] = repo.store_document(
            source_url=f"https://example.com/{role}", title=str(role), content_text=text,
            document_type="news", first_seen_at=cutoff - timedelta(days=1), symbols=["TEST"],
            classification={"role": role} if role else {})
        repo.store_chunks(ids[role], [text])
    assert [r["document_id"] for r in repo.retrieve_passages(
        "TEST", "revenue", cutoff=cutoff, role="company_info")] == [ids["company_info"]]
    assert repo.retrieve_passages("TEST", "revenue", cutoff=cutoff, role="product_event") == []
    # Unclassified documents count as "other", and no role means every role.
    assert [r["document_id"] for r in repo.retrieve_passages(
        "TEST", "revenue", cutoff=cutoff, role="other")] == [ids[None]]
    assert len(repo.retrieve_passages("TEST", "revenue", cutoff=cutoff)) == 3
    # The recency fallback respects the role too.
    fallback = repo.retrieve_passages("TEST", "volatility", cutoff=cutoff, role="public_opinion")
    assert [r["document_id"] for r in fallback] == [ids["public_opinion"]]


def test_retrieval_fill_tops_up_keyword_matches_with_recent_passages(db):
    repo = DatabaseRepository(db)
    cutoff = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    ids = []
    for i, text in enumerate(["Revenue guidance raised", "New phone colours", "CEO interview"]):
        ids.append(repo.store_document(
            source_url=f"https://example.com/{i}", title=text, content_text=text, document_type="news",
            first_seen_at=cutoff - timedelta(hours=10 - i), symbols=["TEST"]))
        repo.store_chunks(ids[-1], [text])
    assert [r["document_id"] for r in repo.retrieve_passages("TEST", "revenue", cutoff=cutoff)] == [ids[0]]
    filled = repo.retrieve_passages("TEST", "revenue", cutoff=cutoff, fill=True)
    # The match ranks first; the rest are the newest non-matching passages, without repeats.
    assert [r["document_id"] for r in filled] == [ids[0], ids[2], ids[1]]
    assert filled[0]["relevance"] > 0 and filled[1]["relevance"] == 0
    assert len(repo.retrieve_passages("TEST", "revenue", cutoff=cutoff, limit=2, fill=True)) == 2
