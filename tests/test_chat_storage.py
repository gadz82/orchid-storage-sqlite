"""Tests for :class:`OrchidSQLiteChatStorage` — in-memory SQLite persistence."""

from __future__ import annotations

import sys
import types

import pytest

from orchid_storage_sqlite.chat_storage import OrchidSQLiteChatStorage

_EXT_PACKAGE = "fake_integrator_migrations_extras"


@pytest.fixture
async def store():
    """Create an in-memory chat store for each test."""
    s = OrchidSQLiteChatStorage(dsn=":memory:")
    await s.init_db()
    yield s
    await s.close()


class TestLifecycle:
    async def test_init_db_is_idempotent(self, store: OrchidSQLiteChatStorage):
        await store.init_db()  # already called in the fixture — must not raise

    async def test_close_is_idempotent(self):
        s = OrchidSQLiteChatStorage(dsn=":memory:")
        await s.init_db()
        await s.close()
        await s.close()

    def test_is_memory_db_variants(self):
        assert OrchidSQLiteChatStorage._is_memory_db(":memory:") is True
        assert OrchidSQLiteChatStorage._is_memory_db(":memory:?cache=shared") is True
        assert OrchidSQLiteChatStorage._is_memory_db("file::memory:") is True
        assert OrchidSQLiteChatStorage._is_memory_db("~/.orchid/chats.db") is False

    def test_forwards_extra_migrations_package(self):
        s = OrchidSQLiteChatStorage(dsn=":memory:", extra_migrations_package="my.integrator.migrations")
        assert s._migrator.extra_migrations_package == "my.integrator.migrations"

    def test_extra_migrations_defaults_to_none(self):
        s = OrchidSQLiteChatStorage(dsn=":memory:")
        assert s._migrator.extra_migrations_package is None


class TestSessions:
    async def test_create_get_list_delete(self, store: OrchidSQLiteChatStorage):
        chat = await store.create_chat("t1", "u1", "Hello")

        assert chat.id
        assert chat.title == "Hello"
        assert chat.is_shared is False

        fetched = await store.get_chat(chat.id)
        assert fetched is not None
        assert fetched.tenant_id == "t1"
        assert fetched.user_id == "u1"

        assert [c.id for c in await store.list_chats("t1", "u1")] == [chat.id]
        assert await store.list_chats("t1", "u2") == []
        assert await store.list_chats("t2", "u1") == []

        await store.delete_chat(chat.id)
        assert await store.get_chat(chat.id) is None
        assert await store.list_chats("t1", "u1") == []

    async def test_default_title(self, store: OrchidSQLiteChatStorage):
        chat = await store.create_chat("t1", "u1")
        assert chat.title == "New chat"

    async def test_list_orders_by_updated_at_desc(self, store: OrchidSQLiteChatStorage):
        first = await store.create_chat("t1", "u1", "first")
        second = await store.create_chat("t1", "u1", "second")

        assert [c.id for c in await store.list_chats("t1", "u1")] == [second.id, first.id]

        await store.update_title(first.id, "renamed")
        assert [c.id for c in await store.list_chats("t1", "u1")] == [first.id, second.id]

    async def test_update_title(self, store: OrchidSQLiteChatStorage):
        chat = await store.create_chat("t1", "u1")
        await store.update_title(chat.id, "Renamed")

        fetched = await store.get_chat(chat.id)
        assert fetched is not None
        assert fetched.title == "Renamed"

    async def test_mark_shared(self, store: OrchidSQLiteChatStorage):
        chat = await store.create_chat("t1", "u1")
        await store.mark_shared(chat.id)

        fetched = await store.get_chat(chat.id)
        assert fetched is not None
        assert fetched.is_shared is True

    async def test_update_title_unknown_chat_is_noop(self, store: OrchidSQLiteChatStorage):
        await store.update_title("missing", "Nope")  # must not raise
        await store.mark_shared("missing")  # must not raise


class TestMessages:
    async def test_add_get_ordering_and_defaults(self, store: OrchidSQLiteChatStorage):
        chat = await store.create_chat("t1", "u1")

        first = await store.add_message(chat.id, "user", "hi")
        second = await store.add_message(chat.id, "assistant", "hello", agents_used=["agent-a"], metadata={"k": "v"})

        messages = await store.get_messages(chat.id)
        assert [m.content for m in messages] == ["hi", "hello"]
        assert first.agents_used == []
        assert first.metadata == {}
        assert second.agents_used == ["agent-a"]
        assert second.metadata == {"k": "v"}

    async def test_limit_and_offset(self, store: OrchidSQLiteChatStorage):
        chat = await store.create_chat("t1", "u1")
        for i in range(5):
            await store.add_message(chat.id, "user", f"m{i}")

        window = await store.get_messages(chat.id, limit=2, offset=1)
        assert [m.content for m in window] == ["m1", "m2"]

    async def test_delete_chat_cascades_messages(self, store: OrchidSQLiteChatStorage):
        chat = await store.create_chat("t1", "u1")
        await store.add_message(chat.id, "user", "hi")

        await store.delete_chat(chat.id)
        assert await store.get_messages(chat.id) == []

    async def test_messages_for_unknown_chat_are_empty(self, store: OrchidSQLiteChatStorage):
        assert await store.get_messages("missing") == []


class TestConversationSummaries:
    async def test_round_trip(self, store: OrchidSQLiteChatStorage):
        chat = await store.create_chat("t1", "u1")

        assert await store.get_conversation_summary(chat.id) is None
        await store.save_conversation_summary(chat.id, "summary one", 1)
        assert await store.get_conversation_summary(chat.id) == "summary one"

        await store.save_conversation_summary(chat.id, "summary two", 2)
        assert await store.get_conversation_summary(chat.id) == "summary two"

    async def test_deleted_chat_drops_summary(self, store: OrchidSQLiteChatStorage):
        chat = await store.create_chat("t1", "u1")
        await store.save_conversation_summary(chat.id, "summary", 1)

        await store.delete_chat(chat.id)
        assert await store.get_conversation_summary(chat.id) is None


# ── Integrator migrations ───────────────────────────────────


def _install_fake_integrator_package() -> None:
    """Register a one-file integrator migration package in ``sys.modules``."""
    if _EXT_PACKAGE in sys.modules:
        return

    pkg = types.ModuleType(_EXT_PACKAGE)
    pkg.__path__ = []

    mod_name = f"{_EXT_PACKAGE}.v001_integrator_table"
    mod = types.ModuleType(mod_name)
    mod.VERSION = "001"
    mod.DESCRIPTION = "Integrator-specific table"

    async def _up(conn, *, dialect: str = "sqlite") -> None:
        await conn.execute("CREATE TABLE IF NOT EXISTS integrator_widgets (id TEXT PRIMARY KEY)")
        await conn.commit()

    async def _down(conn, *, dialect: str = "sqlite") -> None:
        await conn.execute("DROP TABLE IF EXISTS integrator_widgets")
        await conn.commit()

    mod.up = _up
    mod.down = _down
    sys.modules[mod_name] = mod
    pkg.v001_integrator_table = mod  # type: ignore[attr-defined]
    pkg._fake_submodules = [mod_name]  # type: ignore[attr-defined]
    sys.modules[_EXT_PACKAGE] = pkg


@pytest.fixture(autouse=True)
def _patch_pkgutil_iter_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the synthetic integrator package discoverable by ``pkgutil``."""
    import pkgutil

    real_iter = pkgutil.iter_modules

    def _iter(path=None, prefix=""):
        for mod in list(sys.modules.values()):
            if getattr(mod, "__path__", None) is path and hasattr(mod, "_fake_submodules"):
                for sub in mod._fake_submodules:
                    yield (None, sub.rsplit(".", 1)[-1], False)
                return
        yield from real_iter(path=path, prefix=prefix)

    monkeypatch.setattr(pkgutil, "iter_modules", _iter)


class TestIntegratorMigrations:
    async def test_integrator_migration_runs_after_framework(self):
        _install_fake_integrator_package()

        storage = OrchidSQLiteChatStorage(dsn=":memory:", extra_migrations_package=_EXT_PACKAGE)
        await storage.init_db()
        try:
            cursor = await storage._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('chat_sessions', 'mcp_oauth_tokens', "
                "'mcp_client_registrations', 'integrator_widgets')"
            )
            tables = {row[0] async for row in cursor}
            assert tables == {
                "chat_sessions",
                "mcp_oauth_tokens",
                "mcp_client_registrations",
                "integrator_widgets",
            }

            cursor = await storage._conn.execute("SELECT version FROM _migrations ORDER BY version")
            versions = [row[0] async for row in cursor]
            assert versions == ["001", "002", "ext:001"]
        finally:
            await storage.close()

    async def test_without_extras_only_framework_tables(self):
        storage = OrchidSQLiteChatStorage(dsn=":memory:")
        await storage.init_db()
        try:
            cursor = await storage._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('chat_sessions', 'mcp_oauth_tokens', "
                "'mcp_client_registrations', 'integrator_widgets')"
            )
            tables = {row[0] async for row in cursor}
            assert "integrator_widgets" not in tables

            cursor = await storage._conn.execute("SELECT version FROM _migrations ORDER BY version")
            versions = [row[0] async for row in cursor]
            assert versions == ["001", "002"]
        finally:
            await storage.close()
