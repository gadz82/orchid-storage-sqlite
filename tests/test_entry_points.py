"""Entry-point registration tests.

``_register()`` is the callable both entry-point groups point at; these
tests exercise the callable directly and verify the installed package
metadata exposes both groups.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from orchid_ai.checkpointing.factory import _CHECKPOINTER_REGISTRY
from orchid_ai.core.state import OrchidAuthContext
from orchid_ai.events.visibility import _VISIBILITY_FRAGMENT_REGISTRY, build_run_filter_clause

from orchid_storage_sqlite import _register

GROUP_VISIBILITY = "orchid.visibility_fragments"
GROUP_CHECKPOINTERS = "orchid.checkpointers"


class TestRegisterCallable:
    def test_register_populates_both_registries(self):
        _register()
        assert "sqlite" in _VISIBILITY_FRAGMENT_REGISTRY
        assert "sqlite" in _CHECKPOINTER_REGISTRY

    def test_build_run_filter_clause_uses_registered_fragment(self):
        _register()
        auth = OrchidAuthContext(access_token="t", tenant_key="t-1", user_id="u-1")
        fragment = build_run_filter_clause(auth, dialect="sqlite")

        assert ":tenant_key" in fragment.where
        assert fragment.params == {"tenant_key": "t-1", "user_id": "u-1"}

    async def test_build_checkpointer_uses_registered_builder(self, tmp_path):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from orchid_ai.checkpointing import build_checkpointer, shutdown_checkpointer

        _register()
        saver = await build_checkpointer("sqlite", dsn=str(tmp_path / "cp.db"))
        assert isinstance(saver, AsyncSqliteSaver)
        await shutdown_checkpointer(saver)


class TestEntryPointMetadata:
    def test_both_groups_expose_sqlite(self):
        installed = entry_points()
        for group in (GROUP_VISIBILITY, GROUP_CHECKPOINTERS):
            names = {ep.name for ep in installed.select(group=group)}
            assert "sqlite" in names, f"{group} missing sqlite entry point (found: {sorted(names)})"

    def test_entry_point_target_is_register(self):
        installed = entry_points()
        [ep] = [e for e in installed.select(group=GROUP_CHECKPOINTERS) if e.name == "sqlite"]
        assert ep.load() is _register
