# orchid-storage-sqlite — AI Context

## What This Package Is

`orchid-storage-sqlite` is the SQLite storage plugin for the Orchid AI
framework. It provides SQLite-backed implementations of the framework's
storage / persistence ABCs, plus the migrations that own every
framework table:

| Class | Implements | Module |
|-------|-----------|--------|
| `OrchidSQLiteChatStorage` | `OrchidChatStorage` | `chat_storage.py` |
| `OrchidSQLiteConfigStorage` | `OrchidConfigStorage` | `config_storage.py` |
| `OrchidSQLiteMCPTokenStore` | `OrchidMCPTokenStore` | `mcp_token_store.py` |
| `OrchidSQLiteMCPClientRegistrationStore` | `OrchidMCPClientRegistrationStore` | `mcp_client_registration_store.py` |
| `OrchidSQLiteMCPGatewayStateStore` | `OrchidMCPGatewayClientStore` + `OrchidMCPGatewayAuthCodeStore` + `OrchidMCPGatewayTokenStore` | `mcp_gateway_state_store.py` |
| `OrchidSQLiteIngestionManifest` | `OrchidIngestionManifest` | `ingestion_manifest.py` |
| `SQLiteEventStorage` (+ 4 narrow stores) | `OrchidSignalStore` / `OrchidJobStore` / `OrchidScheduleStore` / `OrchidTriggerStore` | `event_storage.py` |
| `SQLiteSignalQueue` | `OrchidSignalQueue` | `event_queue.py` |
| `SQLiteMigrationRunner` | `OrchidMigrationRunner` | `migrations/__init__.py` |
| `_build_sqlite_checkpointer` | LangGraph `BaseCheckpointSaver` | `__init__.py` |
| `_build_sqlite_filter` | `_Filter` (visibility fragment) | `visibility.py` |

Migration `v001_initial_schema` provisions every framework-owned table in
a single pass; `v002_ingestion_manifest` adds the indexing manifest.

## Entry-Point Auto-Registration

The package registers two extension points via Python
`importlib.metadata` entry points:

```toml
[project.entry-points."orchid.visibility_fragments"]
sqlite = "orchid_storage_sqlite:_register"

[project.entry-points."orchid.checkpointers"]
sqlite = "orchid_storage_sqlite:_register"
```

Once installed, `build_run_filter_clause(auth, dialect="sqlite")` and
`build_checkpointer("sqlite", dsn=...)` resolve through the registry —
no manual `register_*` calls.  The registry is populated by
`orchid_ai.plugins.lazy_init_plugins()` (called automatically by the
`Orchid` facade); direct factory calls outside an `Orchid` instance
need `lazy_init_plugins()` or a direct `_register()` call.

The storage classes themselves are **not** auto-registered — consumers
reference them by dotted class path in their YAML:

```yaml
storage:
  class: orchid_storage_sqlite.chat_storage.OrchidSQLiteChatStorage
  dsn: ~/.orchid/chats.db

config_storage:
  enabled: true
  class: orchid_storage_sqlite.config_storage.OrchidSQLiteConfigStorage
  dsn: ~/.orchid/chats.db
```

All classes are also re-exported at package top level
(`orchid_storage_sqlite.OrchidSQLiteChatStorage`,
`orchid_storage_sqlite.SQLiteEventStorage`, …).

## Key Files

| File | Purpose |
|------|---------|
| `chat_storage.py` | `OrchidSQLiteChatStorage` + row mappers |
| `config_storage.py` | `OrchidSQLiteConfigStorage` |
| `mcp_token_store.py` | `OrchidSQLiteMCPTokenStore` |
| `mcp_client_registration_store.py` | `OrchidSQLiteMCPClientRegistrationStore` |
| `mcp_gateway_state_store.py` | `OrchidSQLiteMCPGatewayStateStore` (all three gateway ABCs) |
| `ingestion_manifest.py` | `OrchidSQLiteIngestionManifest` |
| `event_storage.py` | `SQLiteEventStorage` facade + four narrow stores |
| `event_queue.py` | `SQLiteSignalQueue` + `_SQLiteDBTransaction` (ledger of leases/DLQ) |
| `visibility.py` | `_build_sqlite_filter` (named `:param` bind style) |
| `migrations/__init__.py` | `SQLiteMigrationRunner` (dialect + `_migrations` table) |
| `migrations/v001_initial_schema.py` | Initial schema (all framework tables) |
| `migrations/v002_ingestion_manifest.py` | Ingestion manifest table + index |
| `__init__.py` | Entry-point `_register()` callable + checkpointer factory |

## Schema Ownership

All store classes share one database and one migration runner.  The
first `init_db()` on a DSN applies the pending migrations; every later
call is a no-op (`CREATE TABLE IF NOT EXISTS`).  Framework versions are
recorded bare (`"001"`, `"002"`); integrator extras from
`extra_migrations_package` run afterwards with the `ext:` prefix.

JSON columns (`agents_used`, `metadata`, `scopes`, `identity`, `spec`,
`config`, …) are stored as serialised `TEXT`.  The owning store class
performs the `json.dumps` / `json.loads` boundary — callers always see
Python objects, never strings.

## Testing

Tests use `:memory:` SQLite databases — no external services.

```bash
cd orchid-storage-sqlite
pip install -e ".[dev]"
pytest tests/ -x
ruff check orchid_storage_sqlite/ tests/
ruff format orchid_storage_sqlite/ tests/
```

## Common Pitfalls

- **Single-writer engine.** Write-heavy flows (signal queue) serialise
  through transactions; don't parallelise writes on one connection.
- **`:memory:` databases are per-connection.** Re-opening a store with
  `dsn=":memory:"` creates a fresh empty database; use a file (or
  `tmp_path`) when state must survive `init_db()`.
- **WAL + `foreign_keys=ON`** are set by every store's `init_db()`;
  cascade deletes (chat messages, conversation summaries) depend on the
  foreign-keys pragma.
- **`float()` on TEXT columns.** SQLite stores timestamps as `TEXT` in
  some tables and `REAL` in others — row mappers defensively fall back
  to `time.time()` when the value isn't numeric.  Keep that behaviour.
- **Migration v001 is the single root schema.** New framework tables
  belong in a new `vNNN_*.py` module (never edit an applied migration);
  `discover_migrations` scans for `v*` modules exposing `VERSION`, `up`
  and `down`.
- **Event queue leases are time-based.** `dequeue` bumps `attempt` and
  sets `lease_until`; a crashed consumer's message becomes visible again
  after the lease expires.  `nack` schedules a retry; max-attempt rows
  move to `signal_queue_dead_letter`.
- **`SQLiteEventStorage(conn=...)` does not own the connection.**
  `close()` only closes connections opened from `dsn=`; shared-connection
  callers close their own handle.
- **`:memory:` is per-connection.** Constructing `SQLiteEventStorage(dsn=":memory:")`
  and `SQLiteSignalQueue(dsn=":memory:")` yields **two different empty
  databases**; pass the same `conn=` to both (the dispatcher's
  transactional outbox depends on it).
- **Visibility fragment uses named bind params** (`:tenant_key`,
  `:user_id`).  Callers pass `**fragment.params` to aiosqlite — do not
  mix in positional `?` placeholders.
- **The checkpointer keeps a long-lived connection.** The registered
  `sqlite` builder connects once and returns the saver; call
  `shutdown_checkpointer(saver)` (or `saver.aclose()`) to release it.
