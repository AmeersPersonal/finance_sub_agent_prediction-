"""Snowflake RAG with fake connections: no network, no Snowflake account."""

import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from snowflake_rag import __main__ as cli
from snowflake_rag import connection as sf
from snowflake_rag import index as index_module
from snowflake_rag.index import VectorIndex
from snowflake_rag.retrieval import fuse, hybrid_passages
from snowflake_rag.sync import sync

CUTOFF = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
ENV = {
    "SNOWFLAKE_ACCOUNT": "org-acct", "SNOWFLAKE_USER": "svc_rag",
    "SNOWFLAKE_PRIVATE_KEY_FILE": "C:/keys/PRIVATE_KEY_PATH.p8", "SNOWFLAKE_WAREHOUSE": "RAG_WH",
    "SNOWFLAKE_DATABASE": "FINANCE", "SNOWFLAKE_SCHEMA": "RAG",
}


@pytest.fixture
def env(monkeypatch):
    for name in (*sf.REQUIRED, "SNOWFLAKE_ROLE", "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "SNOWFLAKE_EMBED_MODEL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.description = conn, None

    def execute(self, statement, params=None):
        self.conn.statements.append((statement, params))
        if self.conn.fail:
            raise self.conn.fail
        self.description = [("col",)] if statement.lstrip().upper().startswith(("WITH", "SELECT")) else None

    def executemany(self, statement, rows):
        self.conn.statements.append((statement, list(rows)))

    def fetchall(self):
        return self.conn.rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self, rows=(), fail=None):
        self.statements, self.rows, self.fail = [], list(rows), fail

    def cursor(self):
        return FakeCursor(self)


def _row(chunk_id, document_id, relevance=0.0, **extra):
    return {"chunk_id": chunk_id, "document_id": document_id, "relevance": relevance,
            "text": f"chunk {chunk_id}", **extra}


# --- settings and connections --------------------------------------------------

def test_disabled_unless_rag_backend_is_snowflake(monkeypatch):
    monkeypatch.delenv("RAG_BACKEND", raising=False)
    assert not sf.enabled()
    monkeypatch.setenv("RAG_BACKEND", " Snowflake ")
    assert sf.enabled()
    monkeypatch.setenv("RAG_BACKEND", "postgres")
    assert not sf.enabled()


def test_missing_settings_name_variables_not_values(env):
    env.delenv("SNOWFLAKE_USER")
    env.delenv("SNOWFLAKE_WAREHOUSE")
    with pytest.raises(sf.SnowflakeError) as error:
        sf.SnowflakeSettings.from_env()
    assert "SNOWFLAKE_USER, SNOWFLAKE_WAREHOUSE" in str(error.value)
    assert "PRIVATE_KEY_PATH" not in str(error.value)


def test_settings_use_key_pair_auth_and_optional_fields(env):
    options = sf.SnowflakeSettings.from_env().connect_options()
    assert options["authenticator"] == "SNOWFLAKE_JWT"
    assert options["private_key_file"] == ENV["SNOWFLAKE_PRIVATE_KEY_FILE"]
    assert "role" not in options and "private_key_file_pwd" not in options and "password" not in options
    env.setenv("SNOWFLAKE_ROLE", "RAG_READER")
    env.setenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "PRIVATE_PASSPHRASE")
    settings = sf.SnowflakeSettings.from_env()
    assert settings.embed_model == sf.DEFAULT_EMBED_MODEL
    assert settings.connect_options()["role"] == "RAG_READER"
    assert settings.connect_options()["private_key_file_pwd"] == "PRIVATE_PASSPHRASE"


def test_embed_model_name_is_validated(env):
    env.setenv("SNOWFLAKE_EMBED_MODEL", "x'); DROP TABLE RAG_CHUNKS; --")
    with pytest.raises(sf.SnowflakeError, match="SNOWFLAKE_EMBED_MODEL"):
        sf.SnowflakeSettings.from_env()


def _fake_driver(monkeypatch, connect):
    driver = types.ModuleType("snowflake.connector")
    driver.connect = connect
    package = types.ModuleType("snowflake")
    package.connector = driver
    monkeypatch.setitem(sys.modules, "snowflake", package)
    monkeypatch.setitem(sys.modules, "snowflake.connector", driver)
    monkeypatch.setattr(sf, "driver_errors", lambda: ())


def test_connect_failure_hides_credentials(env):
    def refuse(**options):
        raise OSError(f"cannot read {options['private_key_file']}")
    _fake_driver(env, refuse)
    with pytest.raises(sf.SnowflakeError) as error:
        with sf.connect():
            pytest.fail("Should not connect")
    assert "PRIVATE_KEY_PATH" not in str(error.value) and "org-acct" not in str(error.value)


def test_connect_closes_the_session(env):
    opened = []

    class Session:
        closed = False
        def close(self):
            self.closed = True
    _fake_driver(env, lambda **options: opened.append(Session()) or opened[-1])
    with sf.connect() as session:
        assert not session.closed
    assert opened[0].closed


# --- the index -------------------------------------------------------------------

def test_search_filters_point_in_time_and_returns_typed_hits():
    conn = FakeConnection(rows=[(11, 0.82), ("12", "0.5")])
    index = VectorIndex(conn, "snowflake-arctic-embed-l-v2.0")
    hits = index.search(" test ", "revenue guidance", cutoff=CUTOFF,
                        since=CUTOFF - timedelta(days=7), role="public_opinion", k=8)
    assert hits == [(11, 0.82), (12, 0.5)]
    statement, params = conn.statements[0]
    assert "EMBED_TEXT_1024(%(model)s, %(query)s)" in statement
    assert "c.FIRST_SEEN_AT <= TO_TIMESTAMP_TZ(%(cutoff)s)" in statement
    assert "c.PUBLISHED_AT <= TO_TIMESTAMP_TZ(%(cutoff)s)" in statement
    assert "%(since)s" in statement and "c.EVIDENCE_ROLE = %(role)s" in statement
    assert params["ticker"] == "TEST" and params["k"] == 8
    assert params["cutoff"] == CUTOFF.isoformat() and params["role"] == "public_opinion"


def test_search_without_window_or_role_omits_those_filters():
    conn = FakeConnection()
    VectorIndex(conn, "m").search("TEST", "revenue", cutoff=CUTOFF)
    statement, params = conn.statements[0]
    assert "%(since)s" not in statement and "EVIDENCE_ROLE" not in statement
    assert "since" not in params and "role" not in params


def test_empty_query_or_k_skips_snowflake():
    conn = FakeConnection()
    index = VectorIndex(conn, "m")
    assert index.search("TEST", "  ", cutoff=CUTOFF) == []
    assert index.search("TEST", "revenue", cutoff=CUTOFF, k=0) == []
    assert conn.statements == []


def test_upsert_stages_rows_then_merges_with_embeddings():
    conn = FakeConnection()
    index = VectorIndex(conn, "snowflake-arctic-embed-l-v2.0")
    seen = CUTOFF - timedelta(days=1)
    count = index.upsert([
        {"chunk_id": 1, "document_id": 7, "ticker": "nvda", "evidence_role": "company_info",
         "published_at": None, "first_seen_at": seen, "title": "10-Q", "content_text": "Revenue rose."},
        {"chunk_id": 2, "document_id": 8, "ticker": "NVDA", "evidence_role": None,
         "published_at": seen, "first_seen_at": seen, "title": None, "content_text": "Launch."},
    ])
    assert count == 2
    statements = [s for s, _ in conn.statements]
    assert statements[0].startswith("CREATE TEMPORARY TABLE IF NOT EXISTS RAG_CHUNKS_STAGE")
    assert statements[1] == "TRUNCATE TABLE RAG_CHUNKS_STAGE"
    staged = conn.statements[2][1]
    assert staged[0] == (1, 7, "NVDA", "company_info", None, seen.isoformat(), "10-Q", "Revenue rose.")
    assert staged[1][3] == "other"
    merge, params = conn.statements[3]
    assert merge.startswith("MERGE INTO RAG_CHUNKS") and "WHEN NOT MATCHED THEN INSERT" in merge
    assert "EMBED_TEXT_1024" in merge and params == {"model": "snowflake-arctic-embed-l-v2.0"}


def test_upsert_nothing_and_naive_timestamps():
    conn = FakeConnection()
    index = VectorIndex(conn, "m")
    assert index.upsert([]) == 0 and conn.statements == []
    with pytest.raises(ValueError, match="timezone-aware"):
        index.upsert([{"chunk_id": 1, "document_id": 1, "ticker": "T",
                       "first_seen_at": datetime(2026, 10, 1), "content_text": "x"}])


def test_driver_errors_become_safe_snowflake_errors(monkeypatch):
    monkeypatch.setattr(index_module, "driver_errors", lambda: (RuntimeError,))
    conn = FakeConnection(fail=RuntimeError("SQL compilation error near PRIVATE_DETAIL"))
    with pytest.raises(sf.SnowflakeError) as error:
        VectorIndex(conn, "m").search("TEST", "revenue", cutoff=CUTOFF)
    assert "PRIVATE_DETAIL" not in str(error.value)


def test_setup_creates_the_vector_table():
    conn = FakeConnection()
    VectorIndex(conn, "m").setup()
    statement = conn.statements[0][0]
    assert statement.startswith("CREATE TABLE IF NOT EXISTS RAG_CHUNKS")
    assert "VECTOR(FLOAT, 1024)" in statement


# --- fusion and hybrid retrieval --------------------------------------------------

def test_fuse_ranks_agreement_first_and_labels_sources():
    semantic = [_row(1, 10, 0.9), _row(2, 20, 0.8)]
    keyword = [_row(3, 30, 0.4), _row(2, 20, 0.3), _row(4, 40, 0.0)]
    fused = fuse(semantic, keyword, limit=6)
    assert [p["chunk_id"] for p in fused] == [2, 1, 3, 4]
    assert [p["retrieval"] for p in fused] == ["hybrid", "snowflake_vector", "postgres_fulltext", "recency_fill"]
    assert fused[0]["fused_score"] > fused[1]["fused_score"]


def test_fuse_caps_documents_and_limit():
    semantic = [_row(1, 10, 0.9), _row(2, 10, 0.8), _row(3, 10, 0.7), _row(4, 20, 0.6)]
    fused = fuse(semantic, [], limit=3)
    assert [p["chunk_id"] for p in fused] == [1, 2, 4]
    assert fuse(semantic, [], limit=0) == []


def test_fresh_unsynced_keyword_match_still_gets_a_slot():
    semantic = [_row(i, i, 0.9 - i / 100) for i in range(1, 7)]
    fresh = [_row(99, 99, 0.5)]
    assert 99 in [p["chunk_id"] for p in fuse(semantic, fresh, limit=6)]


class FakeRepo:
    def __init__(self, available, keyword):
        self.available, self.keyword, self.calls = available, keyword, []

    def passages_by_chunk_ids(self, ticker, chunk_ids, **kwargs):
        self.calls.append(("by_ids", ticker, list(chunk_ids), kwargs))
        return [_row(c, c * 10) for c in chunk_ids if c in self.available]

    def retrieve_passages(self, ticker, query, **kwargs):
        self.calls.append(("keyword", ticker, query, kwargs))
        return self.keyword


class FakeIndex:
    embed_model = "m"

    def __init__(self, hits):
        self.hits, self.calls = hits, []

    def search(self, ticker, query, **kwargs):
        self.calls.append((ticker, query, kwargs))
        return self.hits


def test_hybrid_reloads_hits_from_postgres_and_drops_unavailable_ones():
    repo = FakeRepo(available={1, 3}, keyword=[_row(5, 50, 0.2)])
    index = FakeIndex(hits=[(1, 0.9), (2, 0.85), (3, 0.7)])  # 2 is superseded or too new
    since = CUTOFF - timedelta(days=7)
    result = hybrid_passages(repo, index, "TEST", "news catalyst", cutoff=CUTOFF,
                             since=since, role="public_opinion", limit=6)
    assert [p["chunk_id"] for p in result] == [1, 5, 3]
    assert result[0]["relevance"] == 0.9 and result[0]["retrieval"] == "snowflake_vector"
    assert index.calls[0][2] == {"cutoff": CUTOFF, "since": since, "role": "public_opinion", "k": 24}
    assert repo.calls[0][2] == [1, 2, 3]
    assert repo.calls[1][3] == {"cutoff": CUTOFF, "since": since, "limit": 6,
                                "role": "public_opinion", "fill": True}


# --- batch sync ------------------------------------------------------------------

class SyncRepo:
    def __init__(self, pending):
        self.pending, self.marked = list(pending), []

    def chunks_to_sync(self, model, *, limit):
        return self.pending[:limit]

    def mark_chunks_synced(self, rows, model):
        self.marked.append((model, [r["chunk_id"] for r in rows]))
        self.pending = [r for r in self.pending if r not in rows]


class SyncIndex:
    embed_model = "m"

    def __init__(self, fail=False):
        self.batches, self.fail = [], fail

    def upsert(self, rows):
        if self.fail:
            raise sf.SnowflakeError("Snowflake query failed.")
        self.batches.append([r["chunk_id"] for r in rows])


def test_sync_runs_batches_until_nothing_is_pending():
    repo, index = SyncRepo([{"chunk_id": i} for i in range(5)]), SyncIndex()
    assert sync(repo, index, batch_size=2) == 5
    assert index.batches == [[0, 1], [2, 3], [4]]
    assert repo.marked == [("m", [0, 1]), ("m", [2, 3]), ("m", [4])]
    assert sync(repo, index) == 0


def test_sync_marks_nothing_when_snowflake_fails_and_respects_max_batches():
    repo = SyncRepo([{"chunk_id": i} for i in range(5)])
    with pytest.raises(sf.SnowflakeError):
        sync(repo, SyncIndex(fail=True))
    assert repo.marked == []
    assert sync(repo, SyncIndex(), batch_size=2, max_batches=1) == 2
    with pytest.raises(ValueError):
        sync(repo, SyncIndex(), batch_size=0)


def test_cli_reports_missing_configuration(env, capsys):
    env.setattr(cli, "load_dotenv", lambda *_: None)
    env.delenv("SNOWFLAKE_ACCOUNT")
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["setup"])
    assert exit_info.value.code == 1
    assert "SNOWFLAKE_ACCOUNT" in capsys.readouterr().err
