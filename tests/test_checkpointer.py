"""Tests for the SQLite checkpointer builder."""

from __future__ import annotations

import pytest

from orchid_storage_sqlite import _build_sqlite_checkpointer, _register


class TestDirectBuilder:
    async def test_missing_dsn_raises(self):
        with pytest.raises(ValueError, match="DSN"):
            await _build_sqlite_checkpointer("")

    async def test_builds_real_saver(self, tmp_path):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from orchid_ai.checkpointing import shutdown_checkpointer

        saver = await _build_sqlite_checkpointer(str(tmp_path / "cp.db"))
        assert isinstance(saver, AsyncSqliteSaver)
        await shutdown_checkpointer(saver)


class TestViaRegistry:
    """``build_checkpointer("sqlite", ...)`` resolves through the entry-point registry."""

    async def test_registered_type_builds_saver(self, tmp_path):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from orchid_ai.checkpointing import build_checkpointer, shutdown_checkpointer

        _register()
        saver = await build_checkpointer("sqlite", dsn=str(tmp_path / "cp.db"))
        assert isinstance(saver, AsyncSqliteSaver)
        await shutdown_checkpointer(saver)

    async def test_registered_type_requires_dsn(self):
        from orchid_ai.checkpointing import build_checkpointer

        _register()
        with pytest.raises(ValueError, match="DSN"):
            await build_checkpointer("sqlite", dsn="")
