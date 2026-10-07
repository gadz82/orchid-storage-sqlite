"""Tests for :class:`OrchidSQLiteConfigStorage` — agent configuration CRUD."""

from __future__ import annotations

import asyncio

import pytest

from orchid_storage_sqlite.config_storage import OrchidSQLiteConfigStorage


@pytest.fixture
async def store():
    """Create an in-memory config store for each test."""
    s = OrchidSQLiteConfigStorage(dsn=":memory:")
    await s.init_db()
    yield s
    await s.close()


class TestSQLiteConfigStorage:
    async def test_crud_operations(self, store: OrchidSQLiteConfigStorage):
        # upsert create
        row = await store.upsert_config("assistant", {"description": "A helpful agent", "prompt": "You are helpful."})
        assert row["name"] == "assistant"
        assert row["created_at"] == row["updated_at"]

        fetched = await store.get_config("assistant")
        assert fetched is not None
        assert fetched["config"]["prompt"] == "You are helpful."

        # upsert replaces the config but preserves created_at
        await store.upsert_config("assistant", {"description": "Better", "prompt": "Hi"})
        replaced = await store.get_config("assistant")
        assert replaced is not None
        assert replaced["created_at"] == row["created_at"]
        assert replaced["config"] == {"description": "Better", "prompt": "Hi"}

        # patch deep-merges + validates
        patched = await store.patch_config("assistant", {"llm": {"temperature": 0.2}})
        assert patched is not None
        assert patched["config"]["description"] == "Better"
        assert patched["config"]["llm"]["temperature"] == 0.2
        assert patched["created_at"] == row["created_at"]

        # patch missing returns None
        assert await store.patch_config("missing", {}) is None

        # delete is idempotent
        await store.delete_config("assistant")
        assert await store.get_config("assistant") is None
        await store.delete_config("assistant")

    async def test_list_orders_by_updated_at_desc(self, store: OrchidSQLiteConfigStorage):
        await store.upsert_config("first", {"description": "First", "prompt": "P"})
        await asyncio.sleep(0.002)
        await store.upsert_config("second", {"description": "Second", "prompt": "P"})

        assert [row["name"] for row in await store.list_configs()] == ["second", "first"]

        await asyncio.sleep(0.002)
        await store.patch_config("first", {"description": "First updated"})
        assert [row["name"] for row in await store.list_configs()] == ["first", "second"]

    async def test_operations_before_init_db(self):
        s = OrchidSQLiteConfigStorage(dsn=":memory:")
        assert await s.list_configs() == []
        assert await s.get_config("missing") is None
        await s.delete_config("missing")  # no-op, must not raise
        with pytest.raises(RuntimeError, match="not initialised"):
            await s.upsert_config("x", {"description": "X", "prompt": "P"})

    async def test_init_db_idempotent(self, store: OrchidSQLiteConfigStorage):
        await store.init_db()  # already initialised — must not raise or wipe rows
        await store.upsert_config("assistant", {"description": "A", "prompt": "P"})
        await store.init_db()
        assert await store.get_config("assistant") is not None

    async def test_close_then_reopen(self):
        s = OrchidSQLiteConfigStorage(dsn=":memory:")
        await s.init_db()
        await s.close()
        await s.close()  # idempotent
