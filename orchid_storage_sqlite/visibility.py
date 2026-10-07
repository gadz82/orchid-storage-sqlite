"""
SQLite run-visibility filter fragment.

Registers a ``build_run_filter_clause`` implementation for the ``sqlite``
dialect that uses named parameters (``:tenant_key``-style) — the
convention consumed by ``aiosqlite``.

Registered via the ``orchid.visibility_fragments`` entry-point group when
the package is installed; no manual ``register_visibility_fragment()``
call is needed.
"""

from __future__ import annotations

from typing import Any

from orchid_ai.events.visibility import _Filter


def _build_sqlite_filter(auth: Any) -> _Filter:
    """Return a ``WHERE`` fragment + named bind params for SQLite.

    Admins short-circuit to a tenant-only filter; everyone else gets
    visibility-by-row.  Cross-tenant access is always rejected because
    the tenant key is ANDed in regardless of role.
    """
    tenant_key = getattr(auth, "tenant_key", "default")
    user_id = getattr(auth, "user_id", "")
    roles = getattr(auth, "roles", frozenset())

    if "admin" in roles:
        return _Filter(
            where="tenant_key = :tenant_key",
            params={"tenant_key": tenant_key},
        )
    return _Filter(
        where=(
            "tenant_key = :tenant_key AND ("
            "visibility = 'tenant' "
            "OR (visibility IN ('actor', 'addressed') "
            "    AND visibility_user_id = :user_id)"
            ")"
        ),
        params={"tenant_key": tenant_key, "user_id": user_id},
    )
