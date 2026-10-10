"""Transactional PostgreSQL persistence for frozen forecasts and source versions.

The caller owns the connection. Methods never commit partially saved forecasts,
never update immutable records, and never include database errors in messages.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from decimal import Decimal
from hashlib import sha256
import re
from typing import Any, Iterable, TYPE_CHECKING
from zoneinfo import ZoneInfo

from database.connection import DatabaseError

if TYPE_CHECKING:
    from ai.schemas import Prediction
    from ai.evaluation import Report


def _json(value: Any) -> Any:
    from psycopg.types.json import Jsonb
    return Jsonb(value)


def persona_output_key(persona) -> str:
    """One row per persona per reasoning mode. The default mode keeps the
    pre-modes key, so rows saved before modes existed keep their meaning."""
    if persona.mode == "default":
        return f"persona:{persona.persona_id}"
    return f"persona:{persona.persona_id}:{persona.mode}"


class DatabaseRepository:
    """A repository using a psycopg connection configured with dict_row."""

    def __init__(self, connection: Any):
        self.connection = connection

    @contextmanager
    def _transaction(self):
        import psycopg
        try:
            with self.connection.transaction():
                yield
        except psycopg.Error:
            raise DatabaseError("Database operation failed.") from None

    def _instrument(self, symbol: str) -> int:
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("Instrument symbol must not be blank.")
        self.connection.execute(
            "INSERT INTO instruments (symbol) VALUES (%s) ON CONFLICT (symbol) DO NOTHING",
            (symbol,),
        )
        row = self.connection.execute(
            "SELECT id FROM instruments WHERE symbol = %s", (symbol,)
        ).fetchone()
        return row["id"]

    def save_prediction(self, prediction: Prediction) -> bool:
        """Save a complete run atomically; True if new, False if identical.

        Reusing a run id with changed contents is rejected. Legacy predictions
        without input_snapshot are supported, but contain no reconstructed inputs.
        """
        payload = prediction.model_dump(mode="json")
        snapshot = payload.get("input_snapshot") or {}
        strategies = snapshot.get("selected_strategies")
        ages = snapshot.get("selected_age_bands")
        if strategies is None:
            strategies = sorted({p.strategy for p in prediction.personas})
        if ages is None:
            ages = sorted({p.age_band for p in prediction.personas})
        with self._transaction():
            instrument_id = self._instrument(prediction.ticker)
            inserted = self.connection.execute(
                """INSERT INTO prediction_runs
                (id, instrument_id, generated_at, cutoff_at, horizon_days,
                 selected_strategies, selected_age_bands, data_as_of, last_price,
                 flat_band_pct, model, prompt_version, frozen_inputs, prediction_payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING RETURNING id""",
                (prediction.id, instrument_id, prediction.generated_at,
                 snapshot.get("evidence_cutoff_at", prediction.generated_at), prediction.horizon_days, strategies, ages,
                 date.fromisoformat(prediction.data_as_of), prediction.last_price,
                 prediction.flat_band_pct, prediction.model, prediction.prompt_version,
                 _json(snapshot), _json(payload)),
            ).fetchone()
            if inserted is None:
                existing = self.connection.execute(
                    "SELECT prediction_payload FROM prediction_runs WHERE id = %s",
                    (prediction.id,),
                ).fetchone()
                if existing["prediction_payload"] != payload:
                    raise DatabaseError("Prediction id already exists with different contents.")
                return False
            self._output(prediction.id, "aggregate", "aggregate", {
                "direction": prediction.direction, "confidence": prediction.confidence,
                "net_score": prediction.net_score, "agreement": prediction.agreement,
                "by_strategy": prediction.by_strategy,
            }, direction=prediction.direction, confidence=prediction.confidence)
            for persona in prediction.personas:
                self._output(prediction.id, persona_output_key(persona), "persona",
                             persona.model_dump(mode="json"), persona_id=persona.persona_id,
                             strategy=persona.strategy, age_band=persona.age_band,
                             direction=persona.view.direction if persona.view else None,
                             confidence=persona.view.conviction if persona.view else None)
            for name, direction in prediction.baselines.items():
                self._output(prediction.id, f"baseline:{name}", "baseline",
                             {"name": name, "direction": direction}, direction=direction)
            if prediction.linear_regression is not None:
                self._output(prediction.id, "regression", "regression",
                             prediction.linear_regression,
                             direction=prediction.baselines.get("linear_regression"),
                             predicted_return_pct=prediction.linear_regression.get("predicted_return_pct"))
        return True

    def _output(self, run_id: str, key: str, kind: str, payload: dict[str, Any], **fields: Any) -> None:
        self.connection.execute(
            """INSERT INTO prediction_outputs
            (run_id, output_key, output_type, persona_id, strategy, age_band,
             direction, confidence, predicted_return_pct, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (run_id, key, kind, fields.get("persona_id"), fields.get("strategy"),
             fields.get("age_band"), fields.get("direction"), fields.get("confidence"),
             fields.get("predicted_return_pct"), _json(payload)),
        )

    def get_prediction(self, prediction_id: str) -> Prediction | None:
        from ai.schemas import Prediction
        with self._transaction():
            row = self.connection.execute(
                "SELECT prediction_payload FROM prediction_runs WHERE id = %s", (prediction_id,)
            ).fetchone()
        return Prediction.model_validate(row["prediction_payload"]) if row else None

    def load_predictions(self, *, ticker: str | None = None, limit: int | None = None) -> list[Prediction]:
        """Load complete runs newest first for the dashboard and evaluation functions."""
        from ai.schemas import Prediction
        if limit is not None and limit < 1:
            raise ValueError("Limit must be positive.")
        sql = "SELECT r.prediction_payload FROM prediction_runs r JOIN instruments i ON i.id = r.instrument_id"
        params: list[Any] = []
        if ticker:
            sql += " WHERE i.symbol = %s"
            params.append(ticker.strip().upper())
        sql += " ORDER BY r.generated_at DESC, r.id DESC"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
        with self._transaction():
            rows = self.connection.execute(sql, params).fetchall()
        return [Prediction.model_validate(row["prediction_payload"]) for row in rows]

    def save_evaluations(self, report: Report, *, provider: str = "yfinance",
                         evaluated_at: datetime | None = None) -> int:
        """Append per-output outcome revisions without modifying forecasts.

        Identical outcome observations are idempotent; corrected prices produce
        a new observation. Legacy Outcome lacks the exact close: mark explicitly
        when the price is reconstructed from its rounded percentage return.
        """
        evaluated_at = evaluated_at or datetime.now(timezone.utc)
        saved = 0
        with self._transaction():
            for outcome in report.outcomes:
                p = outcome.prediction
                stored = self.connection.execute(
                    "SELECT prediction_payload FROM prediction_runs WHERE id = %s FOR UPDATE", (p.id,)
                ).fetchone()
                if stored is None:
                    raise DatabaseError("Save the prediction before its evaluation.")
                if stored["prediction_payload"] != p.model_dump(mode="json"):
                    raise DatabaseError("Evaluation prediction differs from the stored forecast.")
                price = getattr(outcome, "actual_price", None)
                derived = price is None
                if derived:
                    price = p.last_price * (1 + outcome.return_pct / 100)
                # Bind NUMERIC consistently for insertion and equality checks;
                # mixing a float8 comparison with a numeric insert loses digits.
                price = Decimal(str(price))
                outcome_at = datetime.combine(outcome.resolved_on, time(16), ZoneInfo("America/New_York"))
                outputs = self.connection.execute(
                    "SELECT id, direction FROM prediction_outputs WHERE run_id = %s", (p.id,)
                ).fetchall()
                for output in outputs:
                    # actual_price is restated in the share basis of the logged
                    # entry price (splits after the forecast undone), hence 'raw'.
                    details = {"resolved_on": outcome.resolved_on.isoformat(),
                               "price_is_derived": derived,
                               "price_basis": getattr(outcome, "price_basis", "prediction_share_basis"),
                               "split_factor": getattr(outcome, "split_factor", 1.0)}
                    correct = (output["direction"] == outcome.actual
                               if output["direction"] is not None else None)
                    result = self.connection.execute(
                        """INSERT INTO evaluations
                        (run_id, output_id, evaluated_at, outcome_at, provider, adjustment_basis,
                         actual_price, actual_return_pct, actual_direction, correct, payload)
                        SELECT %s, %s, %s, %s, %s, 'raw', %s, %s, %s, %s, %s
                        WHERE NOT EXISTS (
                            SELECT 1 FROM evaluations WHERE run_id = %s AND output_id = %s
                            AND outcome_at = %s AND provider = %s AND adjustment_basis = 'raw'
                            AND actual_price = %s AND actual_return_pct = %s AND actual_direction = %s
                        ) RETURNING id""",
                        (p.id, output["id"], evaluated_at, outcome_at, provider, price,
                         outcome.return_pct, outcome.actual, correct, _json(details),
                         p.id, output["id"], outcome_at, provider, price,
                         outcome.return_pct, outcome.actual),
                    ).fetchone()
                    saved += result is not None
        return saved

    def store_document(self, *, source_url: str, title: str, content_text: str,
                       document_type: str, content_kind: str = "full_text",
                       source_name: str | None = None, published_at: datetime | None = None,
                       first_seen_at: datetime | None = None, symbols: Iterable[str] = (),
                       classification: dict[str, Any] | None = None,
                       metadata: dict[str, Any] | None = None) -> int:
        """Save a source version identified by URL and exact UTF-8 text hash.

        Caller obtains source text and enforces permission to retain it. This
        function performs no fetching, scraping, embedding or Gemini calls.
        """
        digest = sha256(content_text.encode("utf-8")).hexdigest()
        with self._transaction():
            row = self.connection.execute(
                """INSERT INTO documents
                (source_url, source_name, title, document_type, content_kind, content_text,
                 published_at, first_seen_at, content_sha256, classification, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_url, content_sha256) DO NOTHING RETURNING id""",
                (source_url, source_name, title, document_type, content_kind, content_text,
                 published_at, first_seen_at or datetime.now(timezone.utc), digest,
                 _json(classification or {}), _json(metadata or {})),
            ).fetchone()
            if row is None:
                row = self.connection.execute(
                    "SELECT id FROM documents WHERE source_url = %s AND content_sha256 = %s",
                    (source_url, digest),
                ).fetchone()
            for symbol in symbols:
                instrument_id = self._instrument(symbol)
                self.connection.execute(
                    """INSERT INTO document_instruments (document_id, instrument_id)
                    VALUES (%s, %s) ON CONFLICT DO NOTHING""", (row["id"], instrument_id),
                )
        return row["id"]

    def save_price_bars(self, symbol: str, bars: Iterable[dict[str, Any]], *, interval: str,
                        provider: str = "yfinance", adjustment_basis: str = "raw") -> int:
        """Insert bars or refresh corrected values from an equally/newer fetch.

        Unchanged bars are skipped. Provider/adjustment bases remain separate.
        The returned count includes both inserted and corrected records.
        """
        saved = 0
        with self._transaction():
            instrument_id = self._instrument(symbol)
            for bar in bars:
                row = self.connection.execute(
                    """INSERT INTO price_bars
                    (instrument_id, bar_at, interval, provider, adjustment_basis,
                     open, high, low, close, volume, fetched_at, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (instrument_id, bar_at, interval, provider, adjustment_basis)
                    DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high,
                                  low = EXCLUDED.low, close = EXCLUDED.close,
                                  volume = EXCLUDED.volume, fetched_at = EXCLUDED.fetched_at,
                                  metadata = EXCLUDED.metadata
                    WHERE EXCLUDED.fetched_at >= price_bars.fetched_at
                      AND (price_bars.open, price_bars.high, price_bars.low,
                           price_bars.close, price_bars.volume, price_bars.metadata)
                          IS DISTINCT FROM
                          (EXCLUDED.open, EXCLUDED.high, EXCLUDED.low,
                           EXCLUDED.close, EXCLUDED.volume, EXCLUDED.metadata)
                    RETURNING instrument_id""",
                    (instrument_id, bar["bar_at"], interval, provider, adjustment_basis,
                     bar.get("open"), bar.get("high"), bar.get("low"), bar["close"],
                     bar.get("volume"), bar.get("fetched_at") or datetime.now(timezone.utc),
                     _json(bar.get("metadata") or {})),
                ).fetchone()
                saved += row is not None
        return saved

    def save_fundamental_snapshot(self, symbol: str, payload: dict[str, Any], *,
                                  available_at: datetime, provider: str = "yfinance",
                                  period_end: date | None = None,
                                  fetched_at: datetime | None = None,
                                  source_document_id: int | None = None,
                                  metadata: dict[str, Any] | None = None) -> int:
        """Append company data with explicit availability and retrieval dates."""
        with self._transaction():
            instrument_id = self._instrument(symbol)
            row = self.connection.execute(
                """INSERT INTO fundamental_snapshots
                (instrument_id, provider, period_end, available_at, fetched_at,
                 payload, source_document_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (instrument_id, provider, period_end, available_at,
                 fetched_at or datetime.now(timezone.utc), _json(payload),
                 source_document_id, _json(metadata or {})),
            ).fetchone()
        return row["id"]

    def store_chunks(self, document_id: int, chunks: Iterable[str]) -> None:
        """Save deterministic passages once; later runs reuse their IDs."""
        with self._transaction():
            for index, text in enumerate(chunks):
                self.connection.execute(
                    """INSERT INTO document_chunks (document_id, chunk_index, content_text)
                    VALUES (%s, %s, %s) ON CONFLICT (document_id, chunk_index) DO NOTHING""",
                    (document_id, index, text),
                )

    # Latest version per source URL that the instrument's forecast could have seen.
    # Parameters: symbol, cutoff, cutoff, since, since, role, role.
    _AVAILABLE = """WITH available AS (
            SELECT DISTINCT ON (d.source_url) d.*
            FROM documents d JOIN document_instruments di ON di.document_id = d.id
            JOIN instruments i ON i.id = di.instrument_id
            WHERE i.symbol = %s AND d.first_seen_at <= %s
            AND (d.published_at IS NULL OR d.published_at <= %s)
            AND (%s::timestamptz IS NULL OR COALESCE(d.published_at, d.first_seen_at) >= %s)
            AND (%s::text IS NULL OR COALESCE(d.classification->>'role', 'other') = %s)
            ORDER BY d.source_url, d.first_seen_at DESC, d.id DESC
        )"""
    _PASSAGE_FIELDS = """d.id AS document_id, c.id AS chunk_id, d.source_url, d.title,
            d.content_kind, d.document_type, d.classification,
            d.published_at, d.first_seen_at, left(c.content_text, 1600) AS text"""

    def retrieve_passages(self, ticker: str, query: str, *, cutoff: datetime,
                          since: datetime | None = None, limit: int = 6,
                          role: str | None = None, fill: bool = False) -> list[dict]:
        """Rank any matching keyword; use recent passages only if none match.

        `role` restricts to documents classified with that evidence role.
        `fill` tops keyword matches up to `limit` with the most recent other
        passages, so a role with one keyword hit still gets its share of slots.
        Titles and passage bodies are searched without modifying source excerpts.
        The two-passage document cap applies across keyword and fallback results.
        """
        # DOC_QUERIES are keyword bags. Remove query operators before binding OR.
        terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
        keyword_query = " OR ".join('"' + term + '"' for term in terms)
        available, fields = self._AVAILABLE, self._PASSAGE_FIELDS
        filters = (ticker.strip().upper(), cutoff, cutoff, since, since, role, role)
        relevance = """(ts_rank_cd(to_tsvector('english', c.content_text), search.query)
            + ts_rank_cd(to_tsvector('english', d.title), search.query))"""
        with self._transaction():
            matches = self.connection.execute(
                available + ", search AS (SELECT websearch_to_tsquery('english', %s) AS query), ranked AS ("
                + "SELECT " + fields + f""",
                    {relevance} AS relevance,
                    row_number() OVER (PARTITION BY d.id ORDER BY
                        {relevance} DESC,
                        c.chunk_index) AS passage_order
                    FROM available d JOIN document_chunks c ON c.document_id = d.id
                    CROSS JOIN search
                    WHERE to_tsvector('english', c.content_text) @@ search.query
                       OR d.id IN (SELECT id FROM documents
                           WHERE to_tsvector('english', title) @@ search.query)
                ) SELECT * FROM ranked WHERE passage_order <= 2
                  ORDER BY relevance DESC, first_seen_at DESC, chunk_id LIMIT %s""",
                (*filters, keyword_query, limit),
            ).fetchall()
            if limit <= 0 or len(matches) >= limit or (matches and not fill):
                return matches
            return matches + self.connection.execute(
                available + """, selected AS (
                    SELECT document_id, count(*) AS passage_count
                    FROM unnest(%s::bigint[]) AS picked(document_id)
                    GROUP BY document_id
                ), ranked AS (SELECT """ + fields + """,
                    0::real AS relevance,
                    row_number() OVER (PARTITION BY d.id ORDER BY c.chunk_index) AS passage_order
                    FROM available d JOIN document_chunks c ON c.document_id = d.id
                    WHERE c.id <> ALL(%s)
                ) SELECT ranked.* FROM ranked
                  LEFT JOIN selected USING (document_id)
                  WHERE passage_order <= 2 - COALESCE(selected.passage_count, 0)
                  ORDER BY first_seen_at DESC, chunk_id LIMIT %s""",
                (*filters, [m["document_id"] for m in matches],
                 [m["chunk_id"] for m in matches], limit - len(matches)),
            ).fetchall()

    def passages_by_chunk_ids(self, ticker: str, chunk_ids: list[int], *, cutoff: datetime,
                              since: datetime | None = None, role: str | None = None) -> list[dict]:
        """Reload externally ranked chunks under the same availability rules as
        `retrieve_passages`, in the given order, at most two per document.

        A chunk from a superseded source version, a later first-seen date, outside
        the lookback window or with another role is dropped, not trusted.
        """
        if not chunk_ids:
            return []
        filters = (ticker.strip().upper(), cutoff, cutoff, since, since, role, role)
        with self._transaction():
            rows = self.connection.execute(
                self._AVAILABLE + " SELECT " + self._PASSAGE_FIELDS + """
                FROM available d JOIN document_chunks c ON c.document_id = d.id
                WHERE c.id = ANY(%s)""",
                (*filters, list(chunk_ids)),
            ).fetchall()
        by_id = {row["chunk_id"]: row for row in rows}
        kept, per_document = [], {}
        for chunk_id in dict.fromkeys(chunk_ids):
            row = by_id.get(chunk_id)
            if row is None or per_document.get(row["document_id"], 0) >= 2:
                continue
            per_document[row["document_id"]] = per_document.get(row["document_id"], 0) + 1
            kept.append(row)
        return kept

    def chunks_to_sync(self, embedding_model: str, *, limit: int = 500) -> list[dict]:
        """Chunk/ticker pairs not yet copied to the Snowflake index for this model."""
        with self._transaction():
            return self.connection.execute(
                """SELECT c.id AS chunk_id, d.id AS document_id, i.id AS instrument_id,
                    i.symbol AS ticker, COALESCE(d.classification->>'role', 'other') AS evidence_role,
                    d.published_at, d.first_seen_at, d.title, c.content_text
                FROM document_chunks c JOIN documents d ON d.id = c.document_id
                JOIN document_instruments di ON di.document_id = d.id
                JOIN instruments i ON i.id = di.instrument_id
                LEFT JOIN snowflake_synced_chunks s ON s.chunk_id = c.id
                    AND s.instrument_id = i.id AND s.embedding_model = %s
                WHERE s.chunk_id IS NULL
                ORDER BY c.id, i.id LIMIT %s""",
                (embedding_model, limit),
            ).fetchall()

    def mark_chunks_synced(self, rows: Iterable[dict], embedding_model: str) -> int:
        marked = 0
        with self._transaction():
            for row in rows:
                result = self.connection.execute(
                    """INSERT INTO snowflake_synced_chunks (chunk_id, instrument_id, embedding_model)
                    VALUES (%s, %s, %s) ON CONFLICT DO NOTHING RETURNING chunk_id""",
                    (row["chunk_id"], row["instrument_id"], embedding_model),
                ).fetchone()
                marked += result is not None
        return marked

    def save_evidence(self, run_id: str, passage: dict, *, retrieved_at: datetime,
                      strategy: str, cited_by: list[str]) -> None:
        with self._transaction():
            role = passage.get("classification", {}).get("role", "other")
            if role not in {"public_opinion", "company_info", "product_event", "other"}:
                role = "other"
            self.connection.execute(
                """INSERT INTO prediction_evidence
                (run_id, document_id, chunk_id, evidence_role, excerpt_text, retrieved_at, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (run_id, passage["document_id"], passage["chunk_id"], role,
                 passage["text"], retrieved_at,
                 _json({"strategy": strategy, "provided_to_model": True, "cited_by": cited_by,
                        "retrieval": passage.get("retrieval") or (
                            "postgres_fulltext" if passage.get("relevance") else "recency_fill")})),
            )

    def get_price_history(self, ticker: str, *, interval: str = "1d", limit: int = 500) -> list[dict]:
        with self._transaction():
            rows = self.connection.execute(
                """SELECT * FROM (
                    SELECT p.bar_at, p.open, p.high, p.low, p.close, p.volume,
                           p.interval, p.provider, p.adjustment_basis, p.fetched_at
                    FROM price_bars p JOIN instruments i ON i.id = p.instrument_id
                    WHERE i.symbol = %s AND p.interval = %s
                      AND p.provider = 'yfinance' AND p.adjustment_basis = 'total_return'
                    ORDER BY p.bar_at DESC LIMIT %s
                ) recent ORDER BY bar_at""", (ticker.strip().upper(), interval, limit),
            ).fetchall()
        return rows

    def get_model_price_rows(self, ticker: str, *, cutoff: datetime,
                             start_at: datetime | None = None,
                             end_at: datetime | None = None) -> list[dict]:
        """Full ordered daily dataset, rather than the dashboard's capped history."""
        with self._transaction():
            return self.connection.execute(
                """SELECT p.bar_at, p.close, p.volume FROM price_bars p
                JOIN instruments i ON i.id = p.instrument_id
                WHERE i.symbol = %s AND p.interval = '1d'
                  AND p.provider = 'yfinance' AND p.adjustment_basis = 'total_return'
                  AND p.fetched_at <= %s AND p.bar_at <= %s
                  AND (%s::timestamptz IS NULL OR p.bar_at >= %s)
                  AND (%s::timestamptz IS NULL OR p.bar_at <= %s)
                ORDER BY p.bar_at""",
                (ticker.strip().upper(), cutoff, cutoff, start_at, start_at, end_at, end_at),
            ).fetchall()

    def list_documents(self, ticker: str, *, limit: int = 20) -> list[dict]:
        with self._transaction():
            return self.connection.execute(
                """SELECT * FROM (
                    SELECT DISTINCT ON (d.source_url) d.id, d.source_url, d.source_name,
                           d.title, d.document_type, d.content_kind,
                           left(d.content_text, 800) AS excerpt,
                           d.published_at, d.first_seen_at, d.classification
                    FROM documents d JOIN document_instruments di ON di.document_id = d.id
                    JOIN instruments i ON i.id = di.instrument_id
                    WHERE i.symbol = %s
                    ORDER BY d.source_url, d.first_seen_at DESC, d.id DESC
                ) versions ORDER BY first_seen_at DESC LIMIT %s""",
                (ticker.strip().upper(), limit),
            ).fetchall()

    def persona_votes_by_strategy(self) -> dict[str, list[bool]]:
        """Each scored persona row's latest evaluation, grouped by strategy (for auto weights)."""
        with self._transaction():
            rows = self.connection.execute(
                """SELECT o.strategy, latest.correct FROM prediction_outputs o
                CROSS JOIN LATERAL (
                    SELECT e.correct FROM evaluations e WHERE e.output_id = o.id
                    ORDER BY e.evaluated_at DESC, e.id DESC LIMIT 1
                ) latest
                WHERE o.output_type = 'persona' AND latest.correct IS NOT NULL
                ORDER BY o.id"""
            ).fetchall()
        votes: dict[str, list[bool]] = {}
        for row in rows:
            votes.setdefault(row["strategy"], []).append(row["correct"])
        return votes

    def get_evaluations(self, prediction_id: str) -> list[dict]:
        with self._transaction():
            return self.connection.execute(
                """SELECT e.*, o.output_key, o.output_type FROM evaluations e
                LEFT JOIN prediction_outputs o ON o.id = e.output_id
                WHERE e.run_id = %s ORDER BY e.evaluated_at DESC, e.id""", (prediction_id,),
            ).fetchall()
