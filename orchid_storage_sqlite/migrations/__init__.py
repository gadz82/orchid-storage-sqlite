"""
SQLite migration runner.

The runner discovers migrations in ``orchid_storage_sqlite.migrations``
and tracks applied versions in a ``_migrations`` table.
"""

from __future__ import annotations

from typing import Any

from orchid_ai.persistence.migrations.runner import OrchidMigrationRunner

MIGRATIONS_PACKAGE = "orchid_storage_sqlite.migrations"


class SQLiteMigrationRunner(OrchidMigrationRunner):
    """SQLite-specific migration tracking."""

    dialect = "sqlite"
    migrations_package = MIGRATIONS_PACKAGE

    async def ensure_migrations_table(self, conn: Any) -> None:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                version TEXT PRIMARY KEY,
                description TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await conn.commit()

    async def get_applied_versions(self, conn: Any) -> set[str]:
        cursor = await conn.execute("SELECT version FROM _migrations")
        rows = await cursor.fetchall()
        return {r[0] for r in rows}

    async def record_version(self, conn: Any, version: str, description: str) -> None:
        await conn.execute(
            "INSERT INTO _migrations (version, description) VALUES (?, ?)",
            (version, description),
        )
        await conn.commit()

    async def remove_version(self, conn: Any, version: str) -> None:
        await conn.execute("DELETE FROM _migrations WHERE version = ?", (version,))
        await conn.commit()


__all__ = ["MIGRATIONS_PACKAGE", "SQLiteMigrationRunner"]
