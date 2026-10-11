"""Snowflake RAG index commands, run from backend/src/.

    python -m snowflake_rag setup     # create RAG_CHUNKS (idempotent)
    python -m snowflake_rag sync      # embed and copy chunks not yet indexed
    python -m snowflake_rag search NVDA "revenue guidance"   # check ranking by hand
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from database.connection import DatabaseError, connect as connect_postgres
from database.repository import DatabaseRepository
from snowflake_rag.connection import SnowflakeError, SnowflakeSettings, connect
from snowflake_rag.index import VectorIndex
from snowflake_rag.sync import BATCH_SIZE, sync

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m snowflake_rag",
                                     description="Manage the Snowflake RAG index")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="create the index table in Snowflake")
    sync_parser = commands.add_parser("sync", help="embed and copy new PostgreSQL chunks")
    sync_parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    sync_parser.add_argument("--max-batches", type=int)
    search_parser = commands.add_parser("search", help="rank indexed chunks for a query")
    search_parser.add_argument("ticker")
    search_parser.add_argument("query")
    search_parser.add_argument("-k", type=int, default=10)
    args = parser.parse_args(argv)
    load_dotenv(ENV_FILE)

    try:
        settings = SnowflakeSettings.from_env()
        with connect(settings) as snowflake:
            index = VectorIndex(snowflake, settings.embed_model)
            if args.command == "setup":
                index.setup()
                print("Snowflake index table is ready.")
            elif args.command == "sync":
                with connect_postgres() as postgres:
                    count = sync(DatabaseRepository(postgres), index, batch_size=args.batch_size,
                                 max_batches=args.max_batches)
                print(f"Synced {count} chunk/ticker rows with {settings.embed_model}.")
            else:
                hits = index.search(args.ticker, args.query, cutoff=datetime.now(timezone.utc), k=args.k)
                for chunk_id, score in hits:
                    print(f"chunk {chunk_id}  similarity {score:.3f}")
                if not hits:
                    print("No indexed chunks for that ticker; run sync first.")
    except (SnowflakeError, DatabaseError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
