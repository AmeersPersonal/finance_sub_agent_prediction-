"""Synthetic persistence checks; integration uses an opt-in local Unix socket only."""

import asyncio
import os
from collections import Counter
from dataclasses import asdict
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
    "005_document_title_search.sql",
    "006_snowflake_sync.sql",
    "007_oauth_sessions.sql",
    "008_price_bar_revisions.sql",
    "009_user_accounts.sql",
    "010_prediction_jobs.sql",
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


def test_externally_ranked_chunks_obey_the_same_availability_rules(db):
    repo = DatabaseRepository(db)
    cutoff = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    kwargs = dict(source_url="https://example.com/a", title="A", document_type="news",
                  symbols=["TEST"], classification={"role": "public_opinion"})
    old = repo.store_document(content_text="Old", first_seen_at=cutoff - timedelta(days=2), **kwargs)
    new = repo.store_document(content_text="New", first_seen_at=cutoff - timedelta(days=1), **kwargs)
    future = repo.store_document(source_url="https://example.com/future", title="F", content_text="Future",
                                 document_type="news", symbols=["TEST"],
                                 first_seen_at=cutoff + timedelta(days=1))
    long = repo.store_document(source_url="https://example.com/long", title="L", content_text="Long",
                               document_type="news", symbols=["TEST"],
                               classification={"role": "public_opinion"},
                               first_seen_at=cutoff - timedelta(days=1))
    for document_id, texts in ((old, ["old"]), (new, ["new"]), (future, ["future"]),
                               (long, ["one", "two", "three"])):
        repo.store_chunks(document_id, texts)
    chunk = {row["content_text"]: row["id"] for row in db.execute("SELECT id, content_text FROM document_chunks")}
    ranked = [chunk[t] for t in ("three", "old", "future", "new", "one", "two")]
    results = repo.passages_by_chunk_ids("TEST", ranked, cutoff=cutoff)
    # The superseded version and the future document drop out; order is kept; two per document.
    assert [r["text"] for r in results] == ["three", "new", "one"]
    assert repo.passages_by_chunk_ids("TEST", ranked, cutoff=cutoff, role="company_info") == []
    assert repo.passages_by_chunk_ids("OTHER", ranked, cutoff=cutoff) == []
    assert repo.passages_by_chunk_ids("TEST", [], cutoff=cutoff) == []


def test_snowflake_sync_tracking_is_per_chunk_ticker_and_model(db):
    repo = DatabaseRepository(db)
    seen = datetime(2026, 10, 1, tzinfo=timezone.utc)
    document_id = repo.store_document(source_url="https://example.com/s", title="S", content_text="Body",
                                      document_type="news", symbols=["TEST", "PEER"], first_seen_at=seen,
                                      classification={"role": "company_info"})
    repo.store_chunks(document_id, ["Body"])
    pending = repo.chunks_to_sync("model-a")
    assert sorted(r["ticker"] for r in pending) == ["PEER", "TEST"]
    assert {r["evidence_role"] for r in pending} == {"company_info"}
    assert pending[0]["first_seen_at"] == seen and pending[0]["content_text"] == "Body"
    assert repo.mark_chunks_synced(pending[:1], "model-a") == 1
    assert repo.mark_chunks_synced(pending[:1], "model-a") == 0
    assert len(repo.chunks_to_sync("model-a")) == 1
    assert len(repo.chunks_to_sync("model-b")) == 2  # a new embedding model re-syncs everything
    assert [r["ticker"] for r in repo.chunks_to_sync("model-b", ticker="PEER")] == ["PEER"]
    assert repo.mark_chunks_synced([], "model-a") == 0


def test_accounts_are_unique_by_email_and_store_only_hashes(db):
    from oauth.passwords import hash_password
    repo = DatabaseRepository(db)
    hashed = hash_password("correct horse")
    first = repo.create_account(email=" Maya@Example.com ", password_hash=hashed, first_name=" Maya ", last_name="Lopez")
    assert isinstance(first, int)
    assert repo.create_account(email="maya@example.com", password_hash=hashed, first_name="M", last_name="L") is None
    account = repo.get_account("MAYA@example.com")
    assert account == {"id": first, "email": "maya@example.com", "password_hash": hashed,
                       "first_name": "Maya", "last_name": "Lopez"}
    assert repo.get_account("nobody@example.com") is None
    with pytest.raises(DatabaseError):  # the CHECK rejects anything but a scrypt hash
        repo.create_account(email="x@example.com", password_hash="correct horse", first_name="X", last_name="Y")


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


def test_retrieval_searches_historical_and_new_rss_titles_without_rewriting_evidence(db):
    from sources.documents import parse_news_rss

    repo = DatabaseRepository(db)
    cutoff = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    # Recreate the pre-upgrade schema, then insert the same summary-only chunks
    # that older RSS ingestion produced. No re-ingestion should be necessary.
    db.execute("DROP INDEX documents_title_search_idx")
    db.execute("DELETE FROM schema_migrations WHERE name = %s",
               ("005_document_title_search.sql",))
    historical_body = "Management discussed the coming quarter."
    historical = repo.store_document(
        source_url="https://example.com/historical", title="Revenue forecast raised",
        content_text=historical_body, document_type="news", content_kind="excerpt",
        first_seen_at=cutoff - timedelta(days=2), symbols=["TEST"])
    repo.store_chunks(historical, [historical_body])
    original_document = db.execute("SELECT * FROM documents WHERE id = %s", (historical,)).fetchone()
    original_chunk = db.execute(
        "SELECT * FROM document_chunks WHERE document_id = %s", (historical,)).fetchone()
    assert migrate(db) == ["005_document_title_search.sql"]
    assert migrate(db) == []
    assert db.execute("SELECT * FROM documents WHERE id = %s", (historical,)).fetchone() == original_document
    assert db.execute("SELECT * FROM document_chunks WHERE document_id = %s",
                      (historical,)).fetchone() == original_chunk

    document = parse_news_rss(b"""<rss><channel><item>
        <title>Revenue outlook improves</title>
        <link>https://example.com/new-feed-item</link>
        <description>Executives discussed international demand.</description>
        </item></channel></rss>""", "TEST", seen_at=cutoff - timedelta(days=1))[0]
    assert "revenue" not in document.content_text.lower()
    fresh = repo.store_document(**asdict(document), symbols=["TEST"])
    repo.store_chunks(fresh, [document.content_text])
    # A newer unrelated document exposes accidental recency-only fallback.
    unrelated = repo.store_document(
        source_url="https://example.com/unrelated", title="Office picnic",
        content_text="Staff enjoyed the sunshine.", document_type="news",
        first_seen_at=cutoff - timedelta(hours=1), symbols=["TEST"])
    repo.store_chunks(unrelated, ["Staff enjoyed the sunshine."])

    results = repo.retrieve_passages("TEST", "revenue", cutoff=cutoff)
    assert {row["document_id"] for row in results} == {historical, fresh}
    assert all(row["relevance"] > 0 for row in results)
    assert {row["document_id"]: row["text"] for row in results} == {
        historical: historical_body, fresh: document.content_text,
    }
    assert next(row for row in results if row["document_id"] == historical)["chunk_id"] == original_chunk["id"]


@pytest.mark.parametrize("keyword_hits", [0, 1, 2])
@pytest.mark.parametrize("limit", [4, 6])
def test_retrieval_fill_caps_documents_across_keyword_and_fallback_results(db, keyword_hits, limit):
    repo = DatabaseRepository(db)
    cutoff = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    ids = []
    for index in range(3):
        texts = [f"Office discussion topic {n}" for n in range(4)]
        if index == 0:
            texts[:keyword_hits] = [f"Revenue guidance topic {n}" for n in range(keyword_hits)]
        document_id = repo.store_document(
            source_url=f"https://example.com/cap/{index}", title=f"Company report {index}",
            content_text="\n".join(texts), document_type="news", symbols=["TEST"],
            first_seen_at=cutoff - timedelta(hours=index + 1),
            classification={"role": "company_info"})
        repo.store_chunks(document_id, texts)
        ids.append(document_id)

    results = repo.retrieve_passages("TEST", "revenue", cutoff=cutoff,
                                    role="company_info", limit=limit, fill=True)
    assert len(results) == limit
    assert len({row["chunk_id"] for row in results}) == limit
    # The newest document has four chunks, but keyword and fallback selection
    # together may consume only two. Other documents must fill the vacant slots.
    assert Counter(row["document_id"] for row in results) == Counter({
        document_id: 2 for document_id in ids[:limit // 2]
    })
    assert all(row["relevance"] > 0 for row in results[:keyword_hits])
    assert all(row["relevance"] == 0 for row in results[keyword_hits:])
    assert [row["document_id"] for row in results] == [
        document_id for document_id in ids[:limit // 2] for _ in range(2)
    ]


def test_multi_mode_forecast_saves_one_row_per_persona_and_mode(db, snapshot, fake_llm):
    from ai.evaluation import score
    from ai.modes import resolve_modes

    p = asyncio.run(predict("TEST", snapshot=snapshot, llm=fake_llm, modes=resolve_modes("temps")))
    repo = DatabaseRepository(db)
    # Before the key included the mode, the second mode's row broke UNIQUE (run_id, output_key)
    # and the whole save rolled back.
    assert repo.save_prediction(p)
    keys = [r["output_key"] for r in db.execute(
        "SELECT output_key FROM prediction_outputs WHERE run_id = %s AND output_type = 'persona'",
        (p.id,)).fetchall()]
    assert len(keys) == len(set(keys)) == 13 * 3
    assert "persona:long_term:25-39:t0.7" in keys
    assert repo.get_prediction(p.id) == p
    # Every persona-mode row gets its own evaluation.
    closes = pd.Series(float(snapshot.daily["Close"].iloc[-1]) * 1.05,
                       index=[d.date() for d in pd.bdate_range(p.data_as_of, periods=10)])
    later = datetime(2026, 12, 31, 12, tzinfo=timezone.utc)  # after the synthetic outcome date
    report = score([p], {"TEST": closes}, later)
    assert report.scored == 1
    repo.save_evaluations(report, evaluated_at=later)
    evaluated = db.execute(
        "SELECT count(*) AS n FROM evaluations e JOIN prediction_outputs o ON o.id = e.output_id "
        "WHERE e.run_id = %s AND o.output_type = 'persona'", (p.id,)).fetchone()["n"]
    assert evaluated == 13 * 3


def test_default_mode_keeps_the_original_persona_key():
    from ai.schemas import PersonaResult
    from database.repository import persona_output_key

    base = dict(persona_id="day_trader:18-24", strategy="day_trader", age_band="18-24")
    assert persona_output_key(PersonaResult(**base)) == "persona:day_trader:18-24"
    assert persona_output_key(PersonaResult(**base, mode="t1.0")) == "persona:day_trader:18-24:t1.0"


def test_shared_session_store_round_trip_and_expiry(db):
    from contextlib import contextmanager

    from oauth.sessions import DatabaseStore, LOGIN_TTL, SESSION_TTL

    @contextmanager
    def same_connection():
        yield db  # the test schema's connection, in autocommit

    now = [datetime(2026, 10, 9, 12, tzinfo=timezone.utc)]
    store, other_worker = (DatabaseStore(same_connection, clock=lambda: now[0]) for _ in range(2))
    state, verifier = store.begin_login()
    # Only hashes of the state and the session id are stored.
    assert db.execute("SELECT state_hash FROM oauth_pending_logins").fetchone()["state_hash"] != state
    assert other_worker.finish_login(state) == verifier  # another worker completes the login
    assert other_worker.finish_login(state) is None  # once
    session = store.create_session({"sub": "user-1", "email": "user@example.com"})
    assert other_worker.get_session(session) == {"sub": "user-1", "email": "user@example.com"}
    assert session not in str(db.execute("SELECT * FROM oauth_sessions").fetchall())
    store.end_session(session)
    assert other_worker.get_session(session) is None
    # Expired logins and sessions are refused, then swept on the next write.
    late_state, _ = store.begin_login()
    session = store.create_session({"sub": "user-2"})
    now[0] += max(LOGIN_TTL, SESSION_TTL) + timedelta(seconds=1)
    assert store.finish_login(late_state) is None and store.get_session(session) is None
    store.create_session({"sub": "user-3"})
    assert db.execute("SELECT count(*) AS n FROM oauth_sessions").fetchone()["n"] == 1


def test_durable_job_store_round_trip_claim_and_expiry(db):
    from contextlib import contextmanager

    from api.lambda_jobs import JOB_TTL, STALE_AFTER, DatabaseJobStore

    @contextmanager
    def same_connection():
        yield db

    now, sent = [datetime(2026, 10, 9, 12, tzinfo=timezone.utc)], []
    store = DatabaseJobStore(same_connection, sent.append, "k" * 32, clock=lambda: now[0])
    queued = store.submit("user:1", {"ticker": "AAPL"})
    event = sent[0]
    assert queued["status"] == "queued" and event["job_id"] == queued["job_id"] and store.verify(event)
    assert store.get(queued["job_id"], "user:2") is None  # only its creator
    assert store.claim(event["job_id"]) and not store.claim(event["job_id"])  # a replay is a no-op
    store.finish(event["job_id"], result={"id": "p-1", "ticker": "AAPL"})
    done = store.get(event["job_id"], "user:1")
    assert done["status"] == "succeeded" and done["prediction_id"] == "p-1" and done["error"] is None
    # A worker that died mid-run reads as failed; finished rows are swept an hour later.
    stuck = store.submit("user:1", {"ticker": "MSFT"})["job_id"]
    now[0] += STALE_AFTER + timedelta(seconds=1)
    assert store.get(stuck, "user:1")["status"] == "failed"
    now[0] += JOB_TTL
    store.submit("user:1", {"ticker": "NVDA"})
    assert db.execute("SELECT count(*) AS n FROM prediction_jobs WHERE id = %s", (event["job_id"],)).fetchone()["n"] == 0


def test_user_preferences_upsert_and_delete(db):
    repo = DatabaseRepository(db)
    account = "idp.example:user-1"
    assert repo.get_user_preferences(account) is None
    saved = repo.save_user_preferences(account, age_band="25-39", strategy="day_trader",
                                       experience_level="beginner", preferences={"theme": "dark"})
    assert saved["strategy"] == "day_trader" and saved["preferences"] == {"theme": "dark"}
    again = repo.save_user_preferences(account, age_band=None, strategy="long_term",
                                       experience_level=None, preferences={})
    assert again["strategy"] == "long_term" and again["age_band"] is None
    assert again["updated_at"] >= saved["updated_at"]
    with pytest.raises(DatabaseError):  # the table's own checks back up the API's validation
        repo.save_user_preferences(account, age_band="16-17", strategy=None,
                                   experience_level=None, preferences={})
    assert repo.delete_user_preferences(account) and not repo.delete_user_preferences(account)


def test_price_noise_is_not_a_correction_but_real_changes_are(db):
    repo = DatabaseRepository(db)
    at = datetime(2026, 10, 1, 4, tzinfo=timezone.utc)
    first = {"bar_at": at, "open": 229.8, "high": 231.0, "low": 228.5, "close": 230.12345, "volume": 1000, "fetched_at": at}
    later = lambda **change: {**first, "fetched_at": at + timedelta(days=1), **change}  # noqa: E731
    save = lambda bar: repo.save_price_bars("TEST", [bar], interval="1d", adjustment_basis="total_return")  # noqa: E731
    revisions = lambda: db.execute("SELECT count(*) AS n FROM price_bar_revisions").fetchone()["n"]  # noqa: E731
    assert save(first) == 1
    # Yahoo's float jitter (5e-7 relative, the largest seen) on every price: unchanged, nothing archived.
    jitter = 1 + 5.2e-7
    assert save(later(open=229.8 * jitter, high=231.0 / jitter, low=228.5 * jitter, close=230.12345 * jitter)) == 0
    assert revisions() == 0
    assert float(repo.get_price_history("TEST")[0]["close"]) == 230.12345  # the first value is kept
    # A small dividend re-adjustment (0.08%), a volume change and a newly known open are real.
    assert save(later(close=230.12345 * 0.9992)) == 1
    assert save(later(close=230.12345 * 0.9992, volume=1200, fetched_at=at + timedelta(days=2))) == 1
    assert save({**first, "open": None, "fetched_at": at + timedelta(days=3)}) == 1
    assert save({**first, "fetched_at": at + timedelta(days=4)}) == 1  # the open comes back
    assert revisions() == 4


def test_price_corrections_are_archived_and_replayable(db):
    from database.model_data import load_daily_prices_as_known

    repo = DatabaseRepository(db)
    first_fetch = datetime(2026, 10, 2, 21, tzinfo=timezone.utc)
    dates = pd.bdate_range("2026-09-01", periods=20, tz="America/New_York")
    bars = [{"bar_at": at.to_pydatetime(), "close": 100.0 + n, "volume": 1000, "fetched_at": first_fetch}
            for n, at in enumerate(dates)]
    repo.save_price_bars("TEST", bars, interval="1d", adjustment_basis="total_return")
    # A later refresh corrects one close and adds a new bar.
    corrected_at = first_fetch + timedelta(days=3)
    repo.save_price_bars("TEST", [{**bars[5], "close": 555.0, "fetched_at": corrected_at},
                                  {"bar_at": datetime(2026, 9, 29, 4, tzinfo=timezone.utc), "close": 120.0,
                                   "volume": 1000, "fetched_at": corrected_at}],
                         interval="1d", adjustment_basis="total_return")
    revisions = db.execute("SELECT close, change FROM price_bar_revisions").fetchall()
    assert [(float(r["close"]), r["change"]) for r in revisions] == [(105.0, "update")]
    # Unchanged refreshes archive nothing.
    repo.save_price_bars("TEST", bars[:3], interval="1d", adjustment_basis="total_return")
    assert db.execute("SELECT count(*) AS n FROM price_bar_revisions").fetchone()["n"] == 1

    before = load_daily_prices_as_known(repo, "TEST", as_of=first_fetch + timedelta(hours=1))
    assert len(before) == 20 and before["Close"].iloc[5] == 105.0  # the original value
    after = load_daily_prices_as_known(repo, "TEST", as_of=corrected_at + timedelta(hours=1))
    assert len(after) == 21 and after["Close"].iloc[5] == 555.0
    with pytest.raises(psycopg.Error):
        db.execute("DELETE FROM price_bar_revisions")
    # Deleting a bar archives it too, so history before the deletion still has it.
    db.execute("DELETE FROM price_bars WHERE close = 120")
    assert len(load_daily_prices_as_known(repo, "TEST", as_of=corrected_at + timedelta(hours=1))) == 21
