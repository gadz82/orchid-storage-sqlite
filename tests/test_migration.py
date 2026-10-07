"""Tests for the SQLite migrations and the migration runner."""

from __future__ import annotations

import aiosqlite
import pytest

from orchid_storage_sqlite.migrations import SQLiteMigrationRunner, v001_initial_schema, v002_ingestion_manifest

# Every framework-owned table created by v001.
EXPECTED_V001_TABLES = {
    # chat
    "chat_sessions",
    "chat_messages",
    "conversation_summaries",
    # MCP outbound
    "mcp_oauth_tokens",
    "mcp_client_registrations",
    # MCP inbound gateway
    "mcp_gateway_clients",
    "mcp_gateway_auth_codes",
    "mcp_gateway_tokens",
    # events
    "signals",
    "signal_queue",
    "signal_queue_dead_letter",
    "triggers",
    "schedules",
    "job_runs",
    "signal_sources",
    # config
    "agent_configs",
}


@pytest.fixture
async def conn():
    c = await aiosqlite.connect(":memory:")
    yield c
    await c.close()


async def _tables(conn: aiosqlite.Connection) -> set[str]:
    cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in await cursor.fetchall()}


async def _versions(conn: aiosqlite.Connection) -> list[str]:
    cursor = await conn.execute("SELECT version FROM _migrations ORDER BY version")
    return [row[0] for row in await cursor.fetchall()]


class TestRunner:
    async def test_run_up_applies_both_migrations(self, conn):
        applied = await SQLiteMigrationRunner().run_up(conn)

        assert applied == ["001", "002"]
        tables = await _tables(conn)
        assert EXPECTED_V001_TABLES <= tables
        assert "ingestion_manifest" in tables
        assert await _versions(conn) == ["001", "002"]

    async def test_run_up_is_idempotent(self, conn):
        runner = SQLiteMigrationRunner()
        await runner.run_up(conn)

        assert await runner.run_up(conn) == []
        assert await _versions(conn) == ["001", "002"]

    async def test_run_down_to_001_rolls_back_v002(self, conn):
        runner = SQLiteMigrationRunner()
        await runner.run_up(conn)

        rolled_back = await runner.run_down(conn, "001")

        assert rolled_back == ["002"]
        assert "ingestion_manifest" not in await _tables(conn)
        assert await _versions(conn) == ["001"]

    async def test_full_rollback_drops_everything(self, conn):
        runner = SQLiteMigrationRunner()
        await runner.run_up(conn)

        rolled_back = await runner.run_down(conn)

        assert rolled_back == ["002", "001"]
        tables = await _tables(conn)
        assert EXPECTED_V001_TABLES.isdisjoint(tables)
        assert "ingestion_manifest" not in tables


class TestMigrationModules:
    def test_versions_and_descriptions(self):
        assert v001_initial_schema.VERSION == "001"
        assert "initial schema" in v001_initial_schema.DESCRIPTION
        assert v002_ingestion_manifest.VERSION == "002"
        assert "ingestion manifest" in v002_ingestion_manifest.DESCRIPTION.lower()

    async def test_v001_rejects_non_sqlite_dialect(self):
        with pytest.raises(ValueError, match="sqlite"):
            await v001_initial_schema.up(object(), dialect="postgres")

    async def test_v002_rejects_non_sqlite_dialect(self):
        with pytest.raises(ValueError, match="sqlite"):
            await v002_ingestion_manifest.up(object(), dialect="postgres")
