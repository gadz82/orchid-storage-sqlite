"""Tests for the SQLite run-visibility fragment.

The fragment shape is asserted directly against
:func:`orchid_storage_sqlite.visibility._build_sqlite_filter`; the
entry-point registration path is covered in ``test_entry_points.py``.
The SQLite-side CHECK constraint on ``job_runs.visibility`` is verified
here too — it is schema-level behaviour owned by this package.
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid

import aiosqlite
import pytest
from orchid_ai.core.state import OrchidAuthContext

from orchid_storage_sqlite.event_storage import SQLiteEventStorage
from orchid_storage_sqlite.visibility import _build_sqlite_filter


def test_admin_fragment_is_tenant_only() -> None:
    auth = OrchidAuthContext(access_token="t", tenant_key="t-1", user_id="u-7", roles={"admin"})
    fragment = _build_sqlite_filter(auth)

    assert fragment.where == "tenant_key = :tenant_key"
    assert fragment.params == {"tenant_key": "t-1"}


def test_non_admin_fragment_uses_named_params() -> None:
    auth = OrchidAuthContext(access_token="t", tenant_key="t-1", user_id="u-7")
    fragment = _build_sqlite_filter(auth)

    assert ":tenant_key" in fragment.where
    assert ":user_id" in fragment.where
    assert "visibility = 'tenant'" in fragment.where
    assert "visibility IN ('actor', 'addressed')" in fragment.where
    assert fragment.params == {"tenant_key": "t-1", "user_id": "u-7"}


def test_fragment_always_filters_by_tenant() -> None:
    """Cross-tenant access is rejected even for admins — tenant is ANDed in."""
    admin = _build_sqlite_filter(OrchidAuthContext(access_token="t", tenant_key="acme", user_id="u-1", roles={"admin"}))
    user = _build_sqlite_filter(OrchidAuthContext(access_token="t", tenant_key="acme", user_id="u-1"))

    assert "tenant_key = :tenant_key" in admin.where
    assert "tenant_key = :tenant_key" in user.where


def test_fragment_defaults_for_missing_attributes() -> None:
    """Objects without the OrchidAuthContext attributes get safe defaults."""
    fragment = _build_sqlite_filter(object())

    assert ":tenant_key" in fragment.where
    assert fragment.params == {"tenant_key": "default", "user_id": ""}


# ── DB CHECK constraint ─────────────────────────────────────


async def test_db_check_constraint_rejects_inconsistent_row() -> None:
    """SQLite enforces the table-level CHECK that
    ``visibility_user_id`` is NULL iff visibility ∈ {tenant, admin}."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    storage = SQLiteEventStorage(conn=conn)
    await storage.init_db()

    # Need a parent signal row first (FK constraint).
    sig_id = str(_uuid.uuid4())
    now_iso = _dt.datetime.now(tz=_dt.UTC).isoformat()
    await conn.execute(
        "INSERT INTO signals "
        "(signal_id, type, source, payload, tenant_key, occurred_at, persisted_at) "
        "VALUES (?, 'x', 'src', '{}', 't-1', ?, ?)",
        (sig_id, now_iso, now_iso),
    )
    await conn.commit()

    # ``tenant`` visibility with a non-NULL user_id must be rejected.
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO job_runs "
            "(run_id, trigger_id, signal_id, attempt_number, status, "
            " agent_name, parallelism_key, spec, visibility, "
            " visibility_user_id, queued_at) "
            "VALUES (?, 't', ?, 1, 'pending', 'a', 'k', '{}', "
            "        'tenant', 'u-7', ?)",
            (str(_uuid.uuid4()), sig_id, now_iso),
        )

    # And ``actor`` with NULL user_id must be rejected.
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO job_runs "
            "(run_id, trigger_id, signal_id, attempt_number, status, "
            " agent_name, parallelism_key, spec, visibility, "
            " visibility_user_id, queued_at) "
            "VALUES (?, 't', ?, 1, 'pending', 'a', 'k', '{}', "
            "        'actor', NULL, ?)",
            (str(_uuid.uuid4()), sig_id, now_iso),
        )

    # And an unknown visibility level must be rejected.
    with pytest.raises(aiosqlite.IntegrityError):
        await conn.execute(
            "INSERT INTO job_runs "
            "(run_id, trigger_id, signal_id, attempt_number, status, "
            " agent_name, parallelism_key, spec, visibility, "
            " visibility_user_id, queued_at) "
            "VALUES (?, 't', ?, 1, 'pending', 'a', 'k', '{}', "
            "        'world', NULL, ?)",
            (str(_uuid.uuid4()), sig_id, now_iso),
        )
    await conn.close()
