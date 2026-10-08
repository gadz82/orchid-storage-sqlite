# orchid-storage-sqlite

SQLite storage backend package for the [Orchid AI](https://github.com/gadz82/orchid) framework.

## What it provides

SQLite implementations of the framework's storage / persistence ABCs:

- `OrchidSQLiteChatStorage` — chat sessions + messages + conversation summaries
- `OrchidSQLiteConfigStorage` — agent configuration CRUD
- `OrchidSQLiteMCPTokenStore` — per-user MCP OAuth tokens
- `OrchidSQLiteMCPClientRegistrationStore` — RFC 7591 dynamic-client registrations
- `OrchidSQLiteMCPGatewayStateStore` — inbound gateway clients / auth codes / tokens
- `OrchidSQLiteIngestionManifest` — content-hash tracking for idempotent indexing
- `SQLiteEventStorage` (+ four narrow stores) — Pollen + Bloom signal / job /
  schedule / trigger persistence
- `SQLiteSignalQueue` — durable lease-based signal queue with dead-lettering
- `SQLiteMigrationRunner` + migrations v001 (all framework-owned tables) and
  v002 (ingestion manifest)
- A SQLite visibility fragment for `build_run_filter_clause`
- An async SQLite LangGraph checkpointer (registered as the `sqlite` type)

The visibility fragment and checkpointer auto-register through
`importlib.metadata` entry points — no manual `register_*` calls.

## Installation

```bash
pip install orchid-storage-sqlite
```

## Usage

Reference the classes you need in your `orchid.yml`:

```yaml
storage:
  class: orchid_storage_sqlite.chat_storage.OrchidSQLiteChatStorage
  dsn: ~/.orchid/chats.db

config_storage:
  enabled: true
  class: orchid_storage_sqlite.config_storage.OrchidSQLiteConfigStorage
  dsn: ~/.orchid/chats.db

checkpointer:
  type: sqlite
  dsn: ~/.orchid/checkpoints.db
```

For MCP gateway / OAuth deployments, add:

```yaml
mcp_token_store:
  class: orchid_storage_sqlite.mcp_token_store.OrchidSQLiteMCPTokenStore
  dsn: ~/.orchid/chats.db

mcp_client_registration_store:
  class: orchid_storage_sqlite.mcp_client_registration_store.OrchidSQLiteMCPClientRegistrationStore
  dsn: ~/.orchid/chats.db

mcp_gateway_state_store:
  class: orchid_storage_sqlite.mcp_gateway_state_store.OrchidSQLiteMCPGatewayStateStore
  dsn: ~/.orchid/chats.db
```

For the events block (Pollen + Bloom):

```yaml
events:
  enabled: true
  store:
    class: orchid_storage_sqlite.event_storage.SQLiteEventStorage
    extra_args:
      dsn: ~/.orchid/chats.db
  queue:
    class: orchid_storage_sqlite.event_queue.SQLiteSignalQueue
```

Or build any of them programmatically:

```python
from orchid_storage_sqlite import OrchidSQLiteChatStorage, SQLiteSignalQueue, SQLiteEventStorage

storage = OrchidSQLiteChatStorage(dsn="~/.orchid/chats.db")
await storage.init_db()
```

Use `:memory:` for tests and ephemeral runs.

## Schema ownership

The single `v001_initial_schema` migration creates **all** framework
tables (chat, MCP, events, agent_configs, conversation_summaries) in one
pass; `v002_ingestion_manifest` adds the indexing manifest.  All store
classes share the same migration runner, so it does not matter which
class triggers `init_db()` first; subsequent calls become no-ops thanks
to `CREATE TABLE IF NOT EXISTS`.

Integrators can append their own migrations on top of this package's by
setting `extra_migrations_package` (a dotted import path) on the storage
class — their migrations run after the framework's and are recorded with
an `ext:` prefix in the shared `_migrations` table.

## Development

```bash
cd orchid-storage-sqlite
pip install -e ".[dev]"
pytest tests/ -x
ruff check orchid_storage_sqlite/ tests/
```

Tests use `:memory:` / `tmp_path` SQLite databases — no services required.

## License

MIT
