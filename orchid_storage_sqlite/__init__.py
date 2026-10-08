"""SQLite storage plugin for the Orchid AI framework.

Provides SQLite-backed implementations of every framework
storage / persistence ABC:

- :class:`OrchidSQLiteChatStorage` — chat sessions + messages
  (:class:`orchid_ai.persistence.base.OrchidChatStorage`).
- :class:`OrchidSQLiteConfigStorage` — agent configuration CRUD
  (:class:`orchid_ai.config.storage.OrchidConfigStorage`).
- :class:`OrchidSQLiteMCPTokenStore` — per-server OAuth tokens
  (:class:`orchid_ai.core.mcp.OrchidMCPTokenStore`).
- :class:`OrchidSQLiteMCPClientRegistrationStore` — RFC 7591 DCR
  (:class:`orchid_ai.core.mcp.OrchidMCPClientRegistrationStore`).
- :class:`OrchidSQLiteMCPGatewayStateStore` — gateway clients,
  auth codes and tokens (all three
  :mod:`orchid_ai.core.mcp_gateway_state` ABCs).
- :class:`OrchidSQLiteIngestionManifest` — content-hash tracking for
  idempotent indexing
  (:class:`orchid_ai.core.ingestion_manifest.OrchidIngestionManifest`).
- :class:`SQLiteEventStorage` (+ four narrow stores) — events
  signal/job/schedule/trigger persistence.
- :class:`SQLiteSignalQueue` — durable lease-based signal queue.
- :class:`SQLiteMigrationRunner` — migration tracking against a
  ``_migrations`` table (migrations v001 + v002).
- A SQLite checkpointer factory wired into
  :func:`orchid_ai.checkpointing.factory.build_checkpointer` via the
  ``sqlite`` type string.
- A SQLite visibility fragment for
  :func:`orchid_ai.events.visibility.build_run_filter_clause`.

Auto-registers the visibility fragment + checkpointer via
``importlib.metadata`` entry points; storage classes are referenced
by dotted import path in the consumer's YAML.
"""

from __future__ import annotations

import logging

__version__ = "1.1.0"

from .chat_storage import OrchidSQLiteChatStorage
from .config_storage import OrchidSQLiteConfigStorage
from .event_queue import SQLiteSignalQueue
from .event_storage import (
    SQLiteEventStorage,
    SQLiteJobStore,
    SQLiteScheduleStore,
    SQLiteSignalStore,
    SQLiteTriggerStore,
)
from .ingestion_manifest import OrchidSQLiteIngestionManifest
from .mcp_client_registration_store import OrchidSQLiteMCPClientRegistrationStore
from .mcp_gateway_state_store import OrchidSQLiteMCPGatewayStateStore
from .mcp_token_store import OrchidSQLiteMCPTokenStore
from .migrations import SQLiteMigrationRunner
from .visibility import _build_sqlite_filter

__all__ = [
    "OrchidSQLiteChatStorage",
    "OrchidSQLiteConfigStorage",
    "OrchidSQLiteIngestionManifest",
    "OrchidSQLiteMCPClientRegistrationStore",
    "OrchidSQLiteMCPGatewayStateStore",
    "OrchidSQLiteMCPTokenStore",
    "SQLiteEventStorage",
    "SQLiteJobStore",
    "SQLiteMigrationRunner",
    "SQLiteScheduleStore",
    "SQLiteSignalQueue",
    "SQLiteSignalStore",
    "SQLiteTriggerStore",
]

logger = logging.getLogger(__name__)


async def _build_sqlite_checkpointer(dsn: str):
    """Build an async SQLite checkpointer from a file path."""
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    if not dsn:
        raise ValueError("DSN is required for sqlite checkpointer (e.g. ~/.orchid/checkpoints.db)")
    # ``AsyncSqliteSaver.from_conn_string`` is an async *context manager*,
    # not a saver — construct the saver from a long-lived connection so
    # it outlives this call; ``shutdown_checkpointer`` closes it.
    conn = await aiosqlite.connect(dsn)
    checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    logger.info("[orchid-storage-sqlite] Checkpointer ready")
    return checkpointer


def _register() -> None:
    """Entry-point callable — registers the sqlite visibility fragment and checkpointer."""
    try:
        from orchid_ai.events.visibility import register_visibility_fragment

        register_visibility_fragment("sqlite", _build_sqlite_filter)
        logger.debug("[orchid-storage-sqlite] Registered visibility fragment")
    except ImportError:
        logger.debug("[orchid-storage-sqlite] Skipping visibility fragment (not in this orchid-ai version)")

    try:
        from orchid_ai.checkpointing.factory import register_checkpointer

        register_checkpointer("sqlite", _build_sqlite_checkpointer)
        logger.debug("[orchid-storage-sqlite] Registered checkpointer")
    except ImportError:
        logger.debug("[orchid-storage-sqlite] Skipping checkpointer (not in this orchid-ai version)")
