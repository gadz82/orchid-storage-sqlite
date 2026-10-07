"""
Migration v001 — Initial SQLite persistence schema.

Creates every framework-owned table in a single pass:

**Chat persistence**
  - ``chat_sessions`` — one row per user chat thread.
  - ``chat_messages`` — conversation turns, FK-cascade to sessions.
  - ``conversation_summaries`` — running-summary memory per chat.

**MCP outbound (orchid-api as OAuth client to external MCP servers)**
  - ``mcp_oauth_tokens`` — per-user access + refresh tokens.
  - ``mcp_client_registrations`` — per-server discovered auth
    endpoints + DCR (RFC 7591) credentials.

**MCP inbound gateway state (external MCP clients authenticating to
 the gateway via OAuth 2.0 + DCR)**
  - ``mcp_gateway_clients`` — registered inbound DCR clients.
  - ``mcp_gateway_auth_codes`` — in-flight authorization codes with
    upstream-IdP correlation state.
  - ``mcp_gateway_tokens`` — issued gateway access + refresh tokens
    with the resolved identity payload.

**Pollen + Bloom (event-driven activation layer)**
  - ``signals`` — append-only normalised events.
  - ``signal_queue`` — transient queue between dispatcher and
    processor, with leases.
  - ``signal_queue_dead_letter`` — terminal poisoned messages.
  - ``triggers`` — versioned trigger configs.
  - ``schedules`` — cron / interval entries owned by the
    scheduler producer.
  - ``job_runs`` — one row per attempt at running a JobSpec; the
    ``UNIQUE (trigger_id, signal_id, attempt_number)`` constraint
    is what makes Bloom idempotent under queue redelivery.
  - ``signal_sources`` — webhook source registry consumed by the
    HTTP ingestion producer.

**Database-backed agent configuration**
  - ``agent_configs`` — per-agent config rows merged at boot.

SQLite uses ``TEXT`` + ``REAL``.  The JSON columns store serialized
strings — callers (the respective store backends) own the
``json.dumps`` / ``json.loads`` boundary.
"""

from __future__ import annotations

VERSION = "001"
DESCRIPTION = "SQLite initial schema (chat, MCP outbound, MCP inbound gateway, events)"

_SQLITE_UP = [
    # ── Chat persistence ──────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        is_shared INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_sessions_user
        ON chat_sessions (tenant_id, user_id, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        chat_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        agents_used TEXT NOT NULL DEFAULT '[]',
        created_at TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_messages_chat
        ON chat_messages (chat_id, created_at ASC)
    """,
    # ── MCP outbound: per-user OAuth tokens ──────────
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_tokens (
        server_name  TEXT NOT NULL,
        tenant_id    TEXT NOT NULL,
        user_id      TEXT NOT NULL,
        access_token TEXT NOT NULL,
        refresh_token TEXT NOT NULL DEFAULT '',
        expires_at   REAL NOT NULL DEFAULT 0,
        scopes       TEXT NOT NULL DEFAULT '',
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (server_name, tenant_id, user_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_mcp_tokens_user
        ON mcp_oauth_tokens (tenant_id, user_id)
    """,
    # ── MCP outbound: per-server DCR registrations ──
    """
    CREATE TABLE IF NOT EXISTS mcp_client_registrations (
        server_name                             TEXT PRIMARY KEY,
        authorization_endpoint                  TEXT NOT NULL,
        token_endpoint                          TEXT NOT NULL,
        registration_endpoint                   TEXT NOT NULL DEFAULT '',
        issuer                                  TEXT NOT NULL DEFAULT '',
        scopes_supported                        TEXT NOT NULL DEFAULT '',
        token_endpoint_auth_methods_supported   TEXT NOT NULL DEFAULT 'client_secret_post',
        client_id                               TEXT NOT NULL DEFAULT '',
        client_secret                           TEXT NOT NULL DEFAULT '',
        client_id_issued_at                     REAL NOT NULL DEFAULT 0,
        client_secret_expires_at                REAL NOT NULL DEFAULT 0,
        created_at                              TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at                              TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── MCP inbound gateway state ─────────────────────
    """
    CREATE TABLE IF NOT EXISTS mcp_gateway_clients (
        client_id                      TEXT PRIMARY KEY,
        client_name                    TEXT NOT NULL DEFAULT '',
        redirect_uris                  TEXT NOT NULL,
        grant_types                    TEXT NOT NULL,
        response_types                 TEXT NOT NULL,
        token_endpoint_auth_method     TEXT NOT NULL DEFAULT 'none',
        created_at                     REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_gateway_auth_codes (
        code                           TEXT PRIMARY KEY,
        client_id                      TEXT NOT NULL,
        redirect_uri                   TEXT NOT NULL,
        code_challenge                 TEXT NOT NULL,
        code_challenge_method          TEXT NOT NULL,
        upstream_state                 TEXT NOT NULL UNIQUE,
        upstream_code_verifier         TEXT NOT NULL,
        scopes                         TEXT NOT NULL,
        client_state                   TEXT NOT NULL DEFAULT '',
        identity                       TEXT,
        idp_access_token               TEXT NOT NULL DEFAULT '',
        idp_refresh_token              TEXT NOT NULL DEFAULT '',
        idp_expires_at                 REAL NOT NULL DEFAULT 0,
        created_at                     REAL NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_mcp_gateway_auth_codes_created_at
        ON mcp_gateway_auth_codes (created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_gateway_tokens (
        access_token                   TEXT PRIMARY KEY,
        refresh_token                  TEXT NOT NULL UNIQUE,
        client_id                      TEXT NOT NULL,
        subject                        TEXT NOT NULL,
        identity                       TEXT NOT NULL,
        scopes                         TEXT NOT NULL,
        expires_at                     REAL NOT NULL,
        idp_access_token               TEXT NOT NULL DEFAULT '',
        idp_refresh_token              TEXT NOT NULL DEFAULT '',
        idp_expires_at                 REAL NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_mcp_gateway_tokens_expires_at
        ON mcp_gateway_tokens (expires_at)
    """,
    # ── Pollen: signals ───────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS signals (
        signal_id      TEXT PRIMARY KEY,
        type           TEXT NOT NULL,
        source         TEXT NOT NULL,
        payload        TEXT NOT NULL,
        tenant_key     TEXT NOT NULL,
        user_id        TEXT,
        correlation_id TEXT,
        dedupe_key     TEXT,
        identity_claim TEXT,
        chat_binding   TEXT,
        occurred_at    TEXT NOT NULL,
        persisted_at   TEXT NOT NULL,
        relay_status   TEXT NOT NULL DEFAULT 'committed'
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS signals_source_dedupe_idx
        ON signals (source, dedupe_key)
        WHERE dedupe_key IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS signals_type_idx
        ON signals (type, persisted_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS signals_tenant_idx
        ON signals (tenant_key, persisted_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS signals_relay_status_idx
        ON signals (relay_status)
    """,
    # ── Pollen: signal_queue ──────────────────────────
    """
    CREATE TABLE IF NOT EXISTS signal_queue (
        queue_msg_id    TEXT PRIMARY KEY,
        signal_id       TEXT NOT NULL REFERENCES signals(signal_id) ON DELETE CASCADE,
        priority        INTEGER NOT NULL DEFAULT 0,
        enqueued_at     TEXT NOT NULL,
        visible_after   TEXT NOT NULL,
        lease_until     TEXT,
        attempt         INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS signal_queue_visible_idx
        ON signal_queue (visible_after, priority DESC, enqueued_at)
    """,
    # ── Pollen: dead-letter ───────────────────────────
    """
    CREATE TABLE IF NOT EXISTS signal_queue_dead_letter (
        queue_msg_id     TEXT PRIMARY KEY,
        signal_id        TEXT NOT NULL,
        reason           TEXT NOT NULL,
        failed_at        TEXT NOT NULL,
        attempts         INTEGER NOT NULL,
        payload_snapshot TEXT
    )
    """,
    # ── Bloom: triggers ───────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS triggers (
        trigger_id   TEXT NOT NULL,
        version      INTEGER NOT NULL,
        config       TEXT NOT NULL,
        deleted_at   TEXT,
        created_at   TEXT NOT NULL,
        PRIMARY KEY (trigger_id, version)
    )
    """,
    # ── Bloom: schedules ──────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS schedules (
        schedule_id      TEXT PRIMARY KEY,
        trigger_id       TEXT NOT NULL,
        cron             TEXT,
        interval_seconds INTEGER,
        identity_claim   TEXT NOT NULL,
        last_fire_at     TEXT,
        next_fire_at     TEXT,
        enabled          INTEGER NOT NULL DEFAULT 1
    )
    """,
    # ── Bloom: job_runs ───────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS job_runs (
        run_id              TEXT PRIMARY KEY,
        trigger_id          TEXT NOT NULL,
        signal_id           TEXT NOT NULL REFERENCES signals(signal_id),
        attempt_number      INTEGER NOT NULL,
        status              TEXT NOT NULL,
        agent_name          TEXT NOT NULL,
        parallelism_key     TEXT NOT NULL,
        spec                TEXT NOT NULL,
        visibility          TEXT NOT NULL,
        visibility_user_id  TEXT,
        queued_at           TEXT NOT NULL,
        started_at          TEXT,
        finished_at         TEXT,
        result              TEXT,
        error               TEXT,
        next_retry_at       TEXT,
        metadata            TEXT NOT NULL DEFAULT '{}',
        UNIQUE (trigger_id, signal_id, attempt_number),
        CHECK (visibility IN ('actor', 'addressed', 'tenant', 'admin')),
        CHECK (
            (visibility IN ('actor', 'addressed') AND visibility_user_id IS NOT NULL)
            OR
            (visibility IN ('tenant', 'admin')   AND visibility_user_id IS NULL)
        )
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS job_runs_status_idx
        ON job_runs (status, queued_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS job_runs_pkey_idx
        ON job_runs (parallelism_key, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS job_runs_visibility_idx
        ON job_runs (visibility, visibility_user_id)
    """,
    # ── Pollen: signal_sources ────────────────────────
    """
    CREATE TABLE IF NOT EXISTS signal_sources (
        source_id        TEXT PRIMARY KEY,
        validator_class  TEXT NOT NULL,
        validator_config TEXT NOT NULL,
        allowed_types    TEXT NOT NULL,
        enabled          INTEGER NOT NULL DEFAULT 1
    )
    """,
    # ── Agent config storage (database-backed) ───────
    """
    CREATE TABLE IF NOT EXISTS agent_configs (
        name         TEXT PRIMARY KEY,
        config       TEXT NOT NULL,
        created_at   TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    # ── Conversation summaries (running-summary memory) ──
    """
    CREATE TABLE IF NOT EXISTS conversation_summaries (
        chat_id       TEXT PRIMARY KEY REFERENCES chat_sessions(id) ON DELETE CASCADE,
        summary_text  TEXT NOT NULL,
        turn_number   INTEGER NOT NULL DEFAULT 0,
        updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
]

# Reverse order so FK-dependent tables drop before their referents.
_DOWN = [
    "DROP TABLE IF EXISTS signal_sources",
    "DROP TABLE IF EXISTS job_runs",
    "DROP TABLE IF EXISTS schedules",
    "DROP TABLE IF EXISTS triggers",
    "DROP TABLE IF EXISTS signal_queue_dead_letter",
    "DROP TABLE IF EXISTS signal_queue",
    "DROP TABLE IF EXISTS signals",
    "DROP TABLE IF EXISTS mcp_gateway_tokens",
    "DROP TABLE IF EXISTS mcp_gateway_auth_codes",
    "DROP TABLE IF EXISTS mcp_gateway_clients",
    "DROP TABLE IF EXISTS mcp_client_registrations",
    "DROP TABLE IF EXISTS mcp_oauth_tokens",
    "DROP TABLE IF EXISTS conversation_summaries",
    "DROP TABLE IF EXISTS chat_messages",
    "DROP TABLE IF EXISTS chat_sessions",
    "DROP TABLE IF EXISTS agent_configs",
]


async def up(conn, *, dialect: str = "sqlite") -> None:
    if dialect != "sqlite":
        raise ValueError("SQLite migration v001 only supports the sqlite dialect; use orchid-storage-postgres.")
    for sql in _SQLITE_UP:
        await conn.execute(sql)


async def down(conn, *, dialect: str = "sqlite") -> None:
    for sql in _DOWN:
        await conn.execute(sql)
