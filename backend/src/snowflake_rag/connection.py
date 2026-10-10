"""Snowflake settings and connections, configured through the environment.

Key-pair (JWT) authentication only: Snowflake is retiring password-only sign-in
for service users, and a key file keeps the secret out of the process arguments.
Error messages never include the account, user, key path or driver diagnostics.
"""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

DEFAULT_EMBED_MODEL = "snowflake-arctic-embed-l-v2.0"  # 1024 dimensions, for EMBED_TEXT_1024
REQUIRED = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_FILE",
            "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA")
_MODEL = re.compile(r"^[A-Za-z0-9._-]{1,100}$")


class SnowflakeError(RuntimeError):
    """A user-safe Snowflake failure; never includes credentials or driver detail."""


def enabled() -> bool:
    """Whether retrieval should use the Snowflake index (RAG_BACKEND=snowflake)."""
    return (os.getenv("RAG_BACKEND") or "postgres").strip().lower() == "snowflake"


@dataclass(frozen=True)
class SnowflakeSettings:
    account: str
    user: str
    private_key_file: str
    warehouse: str
    database: str
    schema: str
    role: str | None = None
    private_key_passphrase: str | None = None
    embed_model: str = DEFAULT_EMBED_MODEL

    @classmethod
    def from_env(cls) -> SnowflakeSettings:
        missing = [name for name in REQUIRED if not (os.getenv(name) or "").strip()]
        if missing:
            raise SnowflakeError(f"Set {', '.join(missing)} in the backend environment first.")
        model = (os.getenv("SNOWFLAKE_EMBED_MODEL") or DEFAULT_EMBED_MODEL).strip()
        if not _MODEL.match(model):
            raise SnowflakeError("SNOWFLAKE_EMBED_MODEL must be a model name such as "
                                 f"{DEFAULT_EMBED_MODEL}.")
        return cls(
            account=os.environ["SNOWFLAKE_ACCOUNT"].strip(),
            user=os.environ["SNOWFLAKE_USER"].strip(),
            private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"].strip(),
            warehouse=os.environ["SNOWFLAKE_WAREHOUSE"].strip(),
            database=os.environ["SNOWFLAKE_DATABASE"].strip(),
            schema=os.environ["SNOWFLAKE_SCHEMA"].strip(),
            role=(os.getenv("SNOWFLAKE_ROLE") or "").strip() or None,
            private_key_passphrase=os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE") or None,
            embed_model=model,
        )

    def connect_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "account": self.account, "user": self.user, "authenticator": "SNOWFLAKE_JWT",
            "private_key_file": self.private_key_file, "warehouse": self.warehouse,
            "database": self.database, "schema": self.schema,
            "login_timeout": 20, "network_timeout": 60, "paramstyle": "pyformat",
        }
        if self.role:
            options["role"] = self.role
        if self.private_key_passphrase:
            options["private_key_file_pwd"] = self.private_key_passphrase
        return options


def driver_errors() -> tuple[type[BaseException], ...]:
    """The connector's base error, or nothing when the connector isn't installed."""
    try:
        from snowflake.connector.errors import Error
    except ImportError:
        return ()
    return (Error,)


@contextmanager
def connect(settings: SnowflakeSettings | None = None):
    """Open a session and always close it."""
    settings = settings or SnowflakeSettings.from_env()
    try:
        import snowflake.connector
    except ImportError:
        raise SnowflakeError("Install snowflake-connector-python (see src/requirements.txt).") from None
    try:
        connection = snowflake.connector.connect(**settings.connect_options())
    except (*driver_errors(), OSError, ValueError):
        raise SnowflakeError(
            "Snowflake connection failed. Check the account, user, key file, role and warehouse."
        ) from None
    try:
        yield connection
    finally:
        connection.close()
