"""Offline ingestion, grounded-prompt, and persistence service checks."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from ai.agents import DOC_QUERIES
from ai.personas import Strategy
from ai.schemas import PersonaView
from database import service
from sources import DocumentCollection, SourceDocument


@pytest.fixture
def repository(monkeypatch):
    state = SimpleNamespace(events=[], bars=[], fundamentals=[], documents=[], chunks=[],
                            passages=[], retrievals=[], predictions=[], evidence=[], loaded=None,
                            datasets={}, votes={}, unsynced=[])
    class Repo:
        def __init__(self, connection): pass
        def save_price_bars(self, ticker, bars, **kwargs):
            rows = list(bars)
            state.bars.append((ticker, rows, kwargs))
            return len(rows)
        def save_fundamental_snapshot(self, ticker, payload, **kwargs):
            state.fundamentals.append((ticker, payload, kwargs))
        def get_model_price_rows(self, ticker, **kwargs):
            return [row for stored_ticker, bars, opts in state.bars
                    if stored_ticker == ticker and opts['interval'] == '1d'
                    for row in bars]
        def store_document(self, **kwargs):
            state.documents.append(kwargs)
            return len(state.documents)
        def store_chunks(self, document_id, passages):
            state.chunks.append((document_id, list(passages)))
        def retrieve_passages(self, ticker, query, **kwargs):
            state.retrievals.append((ticker, query, kwargs))
            return state.passages
        def chunks_to_sync(self, embedding_model, *, limit):
            return state.unsynced[:limit]
        def mark_chunks_synced(self, rows, embedding_model):
            state.events.append(('synced', [r['chunk_id'] for r in rows]))
            state.unsynced = state.unsynced[len(rows):]
        def passages_by_chunk_ids(self, ticker, chunk_ids, **kwargs):
            state.events.append('reloaded_from_postgres')
            return [p for p in state.passages if p['chunk_id'] in chunk_ids]
        def save_prediction(self, prediction):
            state.predictions.append(prediction)
            return True
        def save_evidence(self, run_id, passage, **kwargs):
            state.evidence.append((run_id, passage, kwargs))
        def get_prediction(self, prediction_id): return state.loaded
        def save_evaluations(self, report): state.events.append('evaluation_saved')
        def get_evaluations(self, prediction_id): return []
        def persona_votes_by_strategy(self): return state.votes
    class Connection:
        """Enough of psycopg for the health check and the real DatasetStore."""
        def execute(self, sql, params=()):
            if sql.startswith('INSERT INTO model_datasets'):
                dataset_id, *_rest, metadata, price_rows = params
                state.datasets[dataset_id] = {'metadata': metadata.obj, 'price_rows': price_rows.obj}
                return SimpleNamespace(fetchone=lambda: None)
            if 'FROM model_datasets' in sql:
                return SimpleNamespace(fetchone=lambda: state.datasets.get(params[0]))
            state.events.append('database_checked')
            return SimpleNamespace(fetchone=lambda: None)
    @contextmanager
    def connect():
        yield Connection()
    monkeypatch.setattr(service, 'connect', connect)
    monkeypatch.setattr(service, 'DatabaseRepository', Repo)
    return state


@pytest.fixture
def offline_sources(monkeypatch, snapshot, repository):
    def fetch(ticker):
        repository.events.append('market_fetched')
        return snapshot
    def documents(ticker, **kwargs):
        repository.events.append('documents_fetched')
        return DocumentCollection()
    monkeypatch.setattr(service, 'fetch_snapshot', fetch)
    monkeypatch.setattr(service, 'fetch_documents', documents)


def test_clean_json_missing_values():
    assert service._clean({'missing': np.nan, 'infinite': float('inf'),
                           'nested': (np.int64(5), float('-inf'))}) == {
                               'missing': None, 'infinite': None, 'nested': [5, None]}


def test_bars_and_fundamentals_preserve_provenance(repository, snapshot):
    snapshot.daily = pd.DataFrame({'Close': [100., np.nan], 'Volume': [10., 20.]},
                                 index=pd.to_datetime(['2026-01-15', '2026-01-16']))
    result = service._persist_snapshot(snapshot, DocumentCollection())
    _, bars, options = repository.bars[0]
    assert len(bars) == 1
    assert bars[0]['bar_at'].utcoffset() == timedelta(hours=-5)
    assert bars[0]['fetched_at'] == snapshot.fetched_at
    assert bars[0]['open'] is None
    assert options == {'interval': '1d', 'adjustment_basis': 'total_return'}
    assert repository.bars[1][2] == {'interval': '5m', 'adjustment_basis': 'total_return'}
    _, payload, provenance = repository.fundamentals[0]
    assert payload['company_info']['shortName'] == 'Test Corp'
    assert provenance['available_at'] == snapshot.fetched_at
    assert 'publication dates unknown' in provenance['metadata']['availability_basis']
    assert result['new_daily_bars'] == 1


def test_evidence_reaches_prompt_and_tracks_supplied_vs_cited(
        monkeypatch, repository, offline_sources, snapshot, fake_llm):
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    document = SourceDocument('https://example.com/release', 'Test earnings',
                              'Synthetic verified earnings passage.', 'news', 'feed_excerpt',
                              'Example', at, at)
    monkeypatch.setattr(service, 'fetch_documents', lambda *_args, **_kwargs:
                        DocumentCollection([document]))
    def passage(chunk_id, text):
        return dict(document_id=1, chunk_id=chunk_id, text=text,
                    source_url=document.source_url, title=document.title,
                    content_kind='feed_excerpt', published_at=at, first_seen_at=at)
    repository.passages = [passage(11, document.content_text), passage(12, 'Additional risk evidence.')]
    original = fake_llm.generate_json
    # Same signature as JsonLLM.generate_json, so a misspelled option still fails loudly.
    async def citing_llm(system, prompt, schema, *, temperature=None, model=None):
        if schema is PersonaView:
            fake_llm.calls.append((system, prompt))
            return PersonaView(direction='up', conviction=.6, rationale='Evidence supports growth',
                               key_factors=[], source_ids=['doc-1-chunk-11', 'invented-id', 'doc-1-chunk-11'])
        return await original(system, prompt, schema, temperature=temperature, model=model)
    fake_llm.generate_json = citing_llm
    p = asyncio.run(service.predict_and_store(' test ', strategies=[Strategy.LONG_TERM],
                                             age_bands=['18-24'], llm=fake_llm))
    assert repository.events[:2] == ['database_checked', 'market_fetched']
    assert repository.documents[0]['content_text'] == document.content_text
    assert repository.chunks == [(1, [document.content_text])]
    assert document.content_text in fake_llm.calls[0][1]
    assert '[doc-1-chunk-11]' in fake_llm.calls[0][1]
    assert p.personas[0].view.source_ids == ['doc-1-chunk-11']
    assert len(p.sources) == 2
    assert p.sources[0]['cited_by'] == [p.personas[0].persona_id]
    assert p.sources[1]['cited_by'] == []
    assert len(repository.evidence) == 2
    assert repository.evidence[0][2]['cited_by'] == [p.personas[0].persona_id]
    assert repository.evidence[1][2]['cited_by'] == []
    assert repository.evidence[0][2]['retrieved_at'].isoformat() == p.input_snapshot['evidence_cutoff_at']
    assert repository.predictions == [p]
    assert p.input_snapshot['regression_dataset']['source'] == 'postgresql'
    assert p.input_snapshot['regression_dataset']['rows'] == len(snapshot.daily)
    # The regression input is a frozen copy of exactly what the personas saw.
    saved = repository.datasets[p.input_snapshot['regression_dataset']['dataset_id']]
    assert saved['metadata']['table'] == 'model_datasets'
    assert saved['price_rows'][-1]['close'] == pytest.approx(float(snapshot.daily['Close'].iloc[-1]))


def test_prompt_labels_each_passage_role(monkeypatch, repository, offline_sources, fake_llm):
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    repository.passages = [
        dict(document_id=1, chunk_id=11, text='Company reports record revenue.',
             source_url='https://www.sec.gov/ex991.htm', title='Press release', content_kind='full_text',
             classification={'role': 'company_info'}, published_at=at, first_seen_at=at),
        dict(document_id=2, chunk_id=21, text='New device reportedly delayed.',
             source_url='https://news.example/rumor', title='Rumor', content_kind='headline',
             classification={'role': 'product_event', 'unconfirmed': True},
             published_at=at, first_seen_at=at),
    ]
    p = asyncio.run(service.predict_and_store('TEST', strategies=[Strategy.LONG_TERM],
                                             age_bands=['18-24'], llm=fake_llm))
    system, prompt = next((s, u) for s, u in fake_llm.calls if 'Persona:' in s)
    assert 'labelled with its role' in system
    assert "[doc-1-chunk-11] Role: company info (the company's own filing or press release)" in prompt
    assert '[doc-2-chunk-21] Role: product event (launch, announcement or rumor); unconfirmed' in prompt
    assert [s['role'] for s in p.sources] == ['company_info', 'product_event']
    assert [n['role'] for n in p.learning['news']] == ['company_info', 'product_event']


def test_no_sources_warns_and_still_saves(repository, offline_sources, fake_llm):
    p = asyncio.run(service.predict_and_store('TEST', strategies=[Strategy.DAY_TRADER],
                                             age_bands=['18-24'], llm=fake_llm))
    assert p.sources == []
    assert any('No online documents retrieved' in warning for warning in p.data_warnings)
    assert repository.predictions == [p]
    assert repository.evidence == []


def test_database_failure_precedes_external_fetch(monkeypatch, offline_sources, repository, fake_llm):
    def fail(): raise RuntimeError('database unavailable')
    monkeypatch.setattr(service, '_check_database', fail)
    with pytest.raises(RuntimeError, match='database unavailable'):
        asyncio.run(service.predict_and_store('TEST', llm=fake_llm))
    assert repository.events == []
    assert fake_llm.calls == []


@pytest.mark.parametrize('ticker,horizon', [('bad ticker', 5), ('TEST', 0), ('TEST', 253)])
def test_invalid_request_precedes_external_calls(ticker, horizon, repository, offline_sources, fake_llm):
    with pytest.raises(ValueError):
        asyncio.run(service.predict_and_store(ticker, horizon_days=horizon, llm=fake_llm))
    assert repository.events == []


def test_retrieval_windows(repository):
    cutoff = datetime(2026, 10, 9, tzinfo=timezone.utc)
    _, warnings = service._retrieve('TEST', set(Strategy), cutoff)
    assert warnings == []  # RAG_BACKEND is unset: PostgreSQL only, nothing to warn about
    windows = {(query, args['role']): args['since'] for _, query, args in repository.retrievals}
    day, options, long = (DOC_QUERIES[s] for s in (Strategy.DAY_TRADER, Strategy.INDEX_OPTIONS, Strategy.LONG_TERM))
    assert len(windows) == 9  # every strategy asks for every role
    assert windows[(day, 'public_opinion')] == cutoff - timedelta(days=7)
    assert windows[(day, 'product_event')] == cutoff - timedelta(days=7)
    assert windows[(options, 'public_opinion')] == cutoff - timedelta(days=90)
    # The latest 10-Q / press release stays relevant past a short news window.
    assert windows[(day, 'company_info')] == cutoff - timedelta(days=140)
    assert windows[(options, 'company_info')] == cutoff - timedelta(days=140)
    assert {windows[(long, role)] for role in service.EVIDENCE_ROLES} == {None}
    assert all(args['cutoff'] == cutoff for _, _, args in repository.retrievals)
    assert all(args['fill'] for _, _, args in repository.retrievals)


@pytest.fixture
def snowflake(monkeypatch):
    """RAG_BACKEND=snowflake with a fake index; `fail_connect` / `fail_search` / `fail_upsert`
    simulate outages."""
    state = SimpleNamespace(searches=[], upserts=[], fail_connect=False, fail_search=False,
                            fail_upsert=False, closed=False)
    class Index:
        def __init__(self, connection, model):
            self.embed_model = model
        def upsert(self, rows):
            if state.fail_upsert:
                raise service.SnowflakeError('Snowflake MERGE failed.')
            state.upserts.append([r['chunk_id'] for r in rows])
        def search(self, ticker, query, **kwargs):
            if state.fail_search:
                raise service.SnowflakeError('Snowflake query failed.')
            state.searches.append((ticker, query, kwargs))
            return [(12, 0.9), (11, 0.8)]
    @contextmanager
    def connect(settings):
        if state.fail_connect:
            raise service.SnowflakeError('Snowflake connection failed.')
        yield object()
        state.closed = True
    monkeypatch.setattr(service, 'snowflake_enabled', lambda: True)
    monkeypatch.setattr(service.SnowflakeSettings, 'from_env',
                        classmethod(lambda cls: SimpleNamespace(embed_model='test-embed')))
    monkeypatch.setattr(service, 'snowflake_connect', connect)
    monkeypatch.setattr(service, 'VectorIndex', Index)
    return state


def _evidence(chunk_id, document_id, relevance=0.0):
    at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return dict(document_id=document_id, chunk_id=chunk_id, text=f'passage {chunk_id}', relevance=relevance,
                source_url=f'https://example.com/{document_id}', title='T', content_kind='excerpt',
                classification={'role': 'public_opinion'}, published_at=at, first_seen_at=at)


def test_snowflake_ranks_then_postgres_reloads_each_role(repository, snowflake):
    repository.passages = [_evidence(11, 1, 0.3), _evidence(12, 2, 0.2)]
    cutoff = datetime(2026, 10, 9, tzinfo=timezone.utc)
    passages, warnings = service._retrieve('TEST', {Strategy.DAY_TRADER}, cutoff)
    assert warnings == [] and snowflake.closed
    assert len(snowflake.searches) == 3  # one per evidence role
    assert snowflake.searches[0][2]['since'] == cutoff - timedelta(days=140)  # company_info window
    assert repository.events.count('reloaded_from_postgres') == 3
    chosen = passages[Strategy.DAY_TRADER]
    assert {p['chunk_id'] for p in chosen} == {11, 12}
    assert {p['retrieval'] for p in chosen} == {'hybrid'}  # both retrievers found both chunks


def test_snowflake_outage_falls_back_to_keyword_search_with_one_warning(repository, snowflake):
    repository.passages = [_evidence(11, 1, 0.3)]
    cutoff = datetime(2026, 10, 9, tzinfo=timezone.utc)
    snowflake.fail_connect = True
    passages, warnings = service._retrieve('TEST', {Strategy.DAY_TRADER}, cutoff)
    assert warnings == [service.SNOWFLAKE_FALLBACK]
    assert [p['chunk_id'] for p in passages[Strategy.DAY_TRADER]] == [11]
    assert 'retrieval' not in passages[Strategy.DAY_TRADER][0]

    snowflake.fail_connect, snowflake.fail_search = False, True
    repository.retrievals.clear()
    _, warnings = service._retrieve('TEST', set(Strategy), cutoff)
    assert warnings == [service.SNOWFLAKE_FALLBACK]  # first failure switches off Snowflake
    assert len(repository.retrievals) == 9 and snowflake.closed


def test_new_chunks_are_indexed_before_the_search(repository, snowflake):
    repository.passages = [_evidence(11, 1, 0.3), _evidence(12, 2, 0.2)]
    repository.unsynced = [{'chunk_id': 12, 'instrument_id': 1}]
    cutoff = datetime(2026, 10, 9, tzinfo=timezone.utc)
    _, warnings = service._retrieve('TEST', {Strategy.DAY_TRADER}, cutoff)
    assert warnings == [] and snowflake.upserts == [[12]]
    assert repository.events.index(('synced', [12])) < repository.events.index('reloaded_from_postgres')
    assert repository.unsynced == []


def test_failed_index_sync_falls_back_to_keyword_search(repository, snowflake):
    repository.passages = [_evidence(11, 1, 0.3)]
    repository.unsynced = [{'chunk_id': 11, 'instrument_id': 1}]
    snowflake.fail_upsert = True
    cutoff = datetime(2026, 10, 9, tzinfo=timezone.utc)
    passages, warnings = service._retrieve('TEST', {Strategy.DAY_TRADER}, cutoff)
    assert warnings == [service.SNOWFLAKE_FALLBACK] and snowflake.searches == []
    assert repository.unsynced  # not marked synced, so the next forecast retries
    assert [p['chunk_id'] for p in passages[Strategy.DAY_TRADER]] == [11]


def test_snowflake_warning_reaches_the_saved_prediction(repository, offline_sources, snowflake, fake_llm):
    snowflake.fail_search = True
    p = asyncio.run(service.predict_and_store('TEST', strategies=[Strategy.DAY_TRADER],
                                             age_bands=['18-24'], llm=fake_llm))
    assert service.SNOWFLAKE_FALLBACK in p.data_warnings
    assert repository.predictions == [p]


def _passages(role, n, start):
    return [{'chunk_id': start + i, 'role': role} for i in range(n)]


def test_mix_roles_round_robins_and_backfills():
    mixed = service.mix_roles({
        'company_info': _passages('company_info', 1, 0),
        'public_opinion': _passages('public_opinion', 5, 10),
        'product_event': _passages('product_event', 2, 20),
    }, 6)
    assert [p['role'] for p in mixed] == [
        'company_info', 'public_opinion', 'product_event',
        'public_opinion', 'product_event', 'public_opinion']


def test_mix_roles_drops_duplicate_chunks_and_handles_empty():
    shared = {'chunk_id': 1, 'role': 'public_opinion'}
    assert service.mix_roles({'public_opinion': [shared], 'product_event': [shared]}, 6) == [shared]
    assert service.mix_roles({}, 6) == []


def test_missing_evaluation_does_not_fetch(monkeypatch, repository):
    monkeypatch.setattr(service, 'fetch_closes', lambda *_: pytest.fail('Missing prediction fetched prices'))
    with pytest.raises(LookupError, match='Prediction not found'):
        asyncio.run(service.evaluate_prediction('missing'))


def test_pending_evaluation_has_no_invented_outcome(monkeypatch, repository):
    repository.loaded = SimpleNamespace(ticker='TEST', data_as_of='2026-10-09')
    monkeypatch.setattr(service, 'fetch_closes', lambda *_: {})
    retry = datetime(2026, 10, 16, 16, 30, tzinfo=timezone.utc)
    waiting = SimpleNamespace(reason='horizon_open', detail='The horizon ends on 2026-10-16.', retry_after=retry)
    monkeypatch.setattr(service, 'score', lambda *_: SimpleNamespace(pending=1, scored=0, pending_details=[waiting]))
    assert asyncio.run(service.evaluate_prediction('pending')) == {
        'prediction_id': 'pending', 'pending': True, 'scored': 0, 'evaluations': [],
        'pending_reason': 'horizon_open', 'pending_detail': 'The horizon ends on 2026-10-16.',
        'retry_after': retry.isoformat()}


def test_forecast_options_reach_predict_and_are_saved(monkeypatch, repository, offline_sources, fake_llm):
    from ai.modes import resolve_modes

    class Feed:
        name = 'fake-websocket'
        async def first_tick(self, ticker, timeout):
            return {'price': 150.0}

    monkeypatch.setattr(service, 'live_feed_from_env', Feed)
    p = asyncio.run(service.predict_and_store(
        'TEST', strategies=[Strategy.DAY_TRADER], age_bands=['18-24'], llm=fake_llm,
        strategy_weights={'day_trader': 2.0}, modes=resolve_modes('temps'), live=True, audit=True))
    assert p.modes == ['t0.2', 't0.7', 't1.0'] and len(p.personas) == 3
    assert p.quote_source == 'fake-websocket' and p.last_price == 150.0
    assert p.audit is not None and p.audit['risk']['level'] in ('low', 'medium', 'high')
    assert repository.predictions == [p]  # the audit is saved with the forecast


def test_auto_weights_come_from_saved_evaluations(monkeypatch, repository, offline_sources, fake_llm):
    captured = {}
    original = service.predict
    async def spy(*args, **kwargs):
        captured['weights'] = kwargs['strategy_weights']
        return await original(*args, **kwargs)
    monkeypatch.setattr(service, 'predict', spy)
    repository.votes = {'long_term': [True] * 80 + [False] * 20, 'day_trader': [True] * 20 + [False] * 80}
    asyncio.run(service.predict_and_store('TEST', strategies=[Strategy.DAY_TRADER], age_bands=['18-24'],
                                          llm=fake_llm, strategy_weights='auto'))
    assert captured['weights']['long_term'] > 1 > captured['weights']['day_trader']
    repository.votes = {}  # nothing scored yet: equal weights
    asyncio.run(service.predict_and_store('TEST', strategies=[Strategy.DAY_TRADER], age_bands=['18-24'],
                                          llm=fake_llm, strategy_weights='auto'))
    assert captured['weights'] is None
