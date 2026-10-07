"""
SQLite config storage — ``OrchidConfigStorage`` over a single aiosqlite file.

Uses aiosqlite for async connection management.  The ``agent_configs`` table
is created by this package's migration v001 when :meth:`init_db` runs.

Configuration::

    config_storage:
      enabled: true
      class: orchid_storage_sqlite.config_storage.OrchidSQLiteConfigStorage
      dsn: ~/.orchid/chats.db
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

import aiosqlite
from orchid_ai.config.schema_agent import OrchidAgentConfig, _deep_merge
from orchid_ai.config.storage import OrchidConfigStorage

from .migrations import SQLiteMigrationRunner

logger = logging.getLogger(__name__)


class OrchidSQLiteConfigStorage(OrchidConfigStorage):
    """Async SQLite storage for agent configurations.

    Reuses the same migration runner as the rest of this package — the
    schema is applied once per database regardless of which storage
    class initiates it.  ``CREATE TABLE IF NOT EXISTS`` makes this safe
    to call multiple times.
    """

    def __init__(self, *, dsn: str) -> None:
        """Keyword-only constructor.

        Parameters
        ----------
        dsn : str
            SQLite database path (e.g. ``"~/.orchid/chats.db"`` or ``":memory:"``).
        """
        self._db_path = os.path.expanduser(dsn)
        self._conn: aiosqlite.Connection | None = None
        self._migrator = SQLiteMigrationRunner()

    async def init_db(self) -> None:
        if self._conn is not None:
            return
        if self._db_path != ":memory:":
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._migrator.run_up(self._conn)
        logger.info("[OrchidConfigStorage:sqlite] Initialised — %s", self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def list_configs(self) -> list[dict]:
        if self._conn is None:
            return []
        cursor = await self._conn.execute(
            "SELECT name, config, created_at, updated_at FROM agent_configs ORDER BY updated_at DESC"
        )
        rows = await cursor.fetchall()
        return [_row_to_config(r) for r in rows]

    async def get_config(self, name: str) -> dict | None:
        if self._conn is None:
            return None
        cursor = await self._conn.execute(
            "SELECT name, config, created_at, updated_at FROM agent_configs WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
        return _row_to_config(row) if row else None

    async def upsert_config(self, name: str, config: dict) -> dict:
        if self._conn is None:
            raise RuntimeError("SQLiteConfigStorage: not initialised. Call init_db() first.")
        now = _now_iso()
        config_json = json.dumps(config)
        await self._conn.execute(
            """INSERT INTO agent_configs (name, config, created_at, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   config = excluded.config,
                   updated_at = excluded.updated_at""",
            (name, config_json, now, now),
        )
        await self._conn.commit()
        return {"name": name, "config": config, "created_at": now, "updated_at": now}

    async def patch_config(self, name: str, patch: dict) -> dict | None:
        if self._conn is None:
            raise RuntimeError("SQLiteConfigStorage: not initialised. Call init_db() first.")
        cursor = await self._conn.execute(
            "SELECT name, config, created_at, updated_at FROM agent_configs WHERE name = ?",
            (name,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        existing = _row_to_config(row)
        merged = _deep_merge(existing["config"], patch)
        OrchidAgentConfig.model_validate(merged)
        now = _now_iso()
        config_json = json.dumps(merged)
        await self._conn.execute(
            "UPDATE agent_configs SET config = ?, updated_at = ? WHERE name = ?",
            (config_json, now, name),
        )
        await self._conn.commit()
        return {"name": name, "config": merged, "created_at": existing["created_at"], "updated_at": now}

    async def delete_config(self, name: str) -> None:
        if self._conn is None:
            return
        await self._conn.execute("DELETE FROM agent_configs WHERE name = ?", (name,))
        await self._conn.commit()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_config(row: aiosqlite.Row) -> dict:
    config = row["config"]
    if isinstance(config, str):
        config = json.loads(config)
    return {
        "name": row["name"],
        "config": config,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
