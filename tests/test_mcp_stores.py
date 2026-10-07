"""Tests for the SQLite MCP stores — token, registration, and gateway state."""

from __future__ import annotations

import time

import pytest
from orchid_ai.core.mcp import OrchidMCPClientRegistration, OrchidMCPTokenRecord
from orchid_ai.core.mcp_gateway_state import (
    OrchidMCPGatewayAuthCode,
    OrchidMCPGatewayClient,
    OrchidMCPGatewayToken,
)

from orchid_storage_sqlite.mcp_client_registration_store import OrchidSQLiteMCPClientRegistrationStore
from orchid_storage_sqlite.mcp_gateway_state_store import OrchidSQLiteMCPGatewayStateStore
from orchid_storage_sqlite.mcp_token_store import OrchidSQLiteMCPTokenStore


@pytest.fixture
async def token_store():
    s = OrchidSQLiteMCPTokenStore(dsn=":memory:")
    await s.init_db()
    yield s
    await s.close()


@pytest.fixture
async def gateway_store():
    s = OrchidSQLiteMCPGatewayStateStore(dsn=":memory:")
    await s.init_db()
    yield s
    await s.close()


def _make_token(
    server_name: str = "ext-crm",
    tenant_id: str = "tenant1",
    user_id: str = "user1",
    access_token: str = "access-token-123",
    **kwargs,
) -> OrchidMCPTokenRecord:
    return OrchidMCPTokenRecord(
        server_name=server_name,
        tenant_id=tenant_id,
        user_id=user_id,
        access_token=access_token,
        **kwargs,
    )


# ── Token store ─────────────────────────────────────────────


class TestSQLiteMCPTokenStore:
    async def test_get_token_returns_none_when_empty(self, token_store: OrchidSQLiteMCPTokenStore):
        assert await token_store.get_token("t", "u", "s") is None

    async def test_save_and_get_token(self, token_store: OrchidSQLiteMCPTokenStore):
        await token_store.save_token(_make_token())

        loaded = await token_store.get_token("tenant1", "user1", "ext-crm")
        assert loaded is not None
        assert loaded.server_name == "ext-crm"
        assert loaded.access_token == "access-token-123"
        assert loaded.tenant_id == "tenant1"
        assert loaded.user_id == "user1"

    async def test_save_token_upserts(self, token_store: OrchidSQLiteMCPTokenStore):
        await token_store.save_token(_make_token(access_token="old-token"))
        await token_store.save_token(_make_token(access_token="new-token"))

        loaded = await token_store.get_token("tenant1", "user1", "ext-crm")
        assert loaded is not None
        assert loaded.access_token == "new-token"

    async def test_delete_token(self, token_store: OrchidSQLiteMCPTokenStore):
        await token_store.save_token(_make_token())
        assert await token_store.delete_token("tenant1", "user1", "ext-crm") is True
        assert await token_store.get_token("tenant1", "user1", "ext-crm") is None

    async def test_delete_nonexistent_returns_false(self, token_store: OrchidSQLiteMCPTokenStore):
        assert await token_store.delete_token("t", "u", "nonexistent") is False

    async def test_list_tokens(self, token_store: OrchidSQLiteMCPTokenStore):
        await token_store.save_token(_make_token(server_name="server-a"))
        await token_store.save_token(_make_token(server_name="server-b"))
        await token_store.save_token(_make_token(server_name="server-c", tenant_id="other-tenant"))

        tokens = await token_store.list_tokens("tenant1", "user1")
        assert {t.server_name for t in tokens} == {"server-a", "server-b"}

    async def test_init_db_idempotent(self, token_store: OrchidSQLiteMCPTokenStore):
        await token_store.init_db()  # already called in the fixture — must not raise

    async def test_preserves_refresh_token_and_scopes(self, token_store: OrchidSQLiteMCPTokenStore):
        await token_store.save_token(
            _make_token(
                refresh_token="refresh-abc",
                scopes="openid crm.read",
                expires_at=time.time() + 3600,
            )
        )

        loaded = await token_store.get_token("tenant1", "user1", "ext-crm")
        assert loaded is not None
        assert loaded.refresh_token == "refresh-abc"
        assert loaded.scopes == "openid crm.read"
        assert loaded.expires_at > 0

    async def test_different_users_isolated(self, token_store: OrchidSQLiteMCPTokenStore):
        await token_store.save_token(_make_token(user_id="alice", access_token="alice-token"))
        await token_store.save_token(_make_token(user_id="bob", access_token="bob-token"))

        alice = await token_store.get_token("tenant1", "alice", "ext-crm")
        bob = await token_store.get_token("tenant1", "bob", "ext-crm")
        assert alice is not None and alice.access_token == "alice-token"
        assert bob is not None and bob.access_token == "bob-token"

    async def test_cleanup_expired_purges_only_past_rows(self, token_store: OrchidSQLiteMCPTokenStore):
        now = time.time()
        await token_store.save_token(_make_token(server_name="expired", expires_at=now - 100))
        await token_store.save_token(_make_token(server_name="live", expires_at=now + 3600))
        await token_store.save_token(_make_token(server_name="no-expiry", expires_at=0.0))

        assert await token_store.cleanup_expired() == 1
        assert await token_store.get_token("tenant1", "user1", "expired") is None
        assert await token_store.get_token("tenant1", "user1", "live") is not None
        assert await token_store.get_token("tenant1", "user1", "no-expiry") is not None

    async def test_cleanup_expired_respects_explicit_cutoff(self, token_store: OrchidSQLiteMCPTokenStore):
        base = 1_000_000.0
        await token_store.save_token(_make_token(server_name="will-expire-soon", expires_at=base + 60))
        await token_store.save_token(_make_token(server_name="future", expires_at=base + 7200))

        assert await token_store.cleanup_expired(before=base + 120) == 1
        assert await token_store.get_token("tenant1", "user1", "will-expire-soon") is None
        assert await token_store.get_token("tenant1", "user1", "future") is not None

    async def test_cleanup_expired_returns_zero_on_empty_store(self, token_store: OrchidSQLiteMCPTokenStore):
        assert await token_store.cleanup_expired() == 0


# ── Client registration store ───────────────────────────────


def _registration(server_name: str = "crm", **kwargs) -> OrchidMCPClientRegistration:
    values = {
        "authorization_endpoint": "https://idp.example.com/oauth2/authorize",
        "token_endpoint": "https://idp.example.com/oauth2/token",
        "registration_endpoint": "https://idp.example.com/oauth2/register",
        "issuer": "https://idp.example.com",
        "scopes_supported": "openid mcp.read",
        "client_id": "dyn-abc",
        "client_secret": "s3kr3t",
        "client_id_issued_at": 1_700_000_000.0,
        "client_secret_expires_at": 0.0,
    }
    values.update(kwargs)
    return OrchidMCPClientRegistration(server_name=server_name, **values)


class TestSQLiteMCPClientRegistrationStore:
    async def test_round_trip_save_get(self):
        store = OrchidSQLiteMCPClientRegistrationStore(dsn=":memory:")
        await store.init_db()
        try:
            record = _registration()
            await store.save(record)

            loaded = await store.get("crm")
            assert loaded is not None
            assert loaded.client_id == "dyn-abc"
            assert loaded.client_secret == "s3kr3t"
            assert loaded.authorization_endpoint == record.authorization_endpoint
            assert loaded.token_endpoint_auth_methods_supported == "client_secret_post"
        finally:
            await store.close()

    async def test_save_is_upsert(self):
        store = OrchidSQLiteMCPClientRegistrationStore(dsn=":memory:")
        await store.init_db()
        try:
            await store.save(_registration(client_id="old-id"))
            await store.save(_registration(client_id="new-id", client_secret="new-secret"))

            loaded = await store.get("crm")
            assert loaded is not None
            assert loaded.client_id == "new-id"
            assert loaded.client_secret == "new-secret"
        finally:
            await store.close()

    async def test_get_returns_none_for_missing(self):
        store = OrchidSQLiteMCPClientRegistrationStore(dsn=":memory:")
        await store.init_db()
        try:
            assert await store.get("unknown") is None
        finally:
            await store.close()

    async def test_delete_returns_true_only_on_hit(self):
        store = OrchidSQLiteMCPClientRegistrationStore(dsn=":memory:")
        await store.init_db()
        try:
            await store.save(_registration())
            assert await store.delete("crm") is True
            assert await store.delete("crm") is False
            assert await store.get("crm") is None
        finally:
            await store.close()


# ── Gateway state store ─────────────────────────────────────


def _client(
    client_id: str = "cli-abc",
    *,
    redirect_uris: list[str] | None = None,
    grant_types: list[str] | None = None,
    response_types: list[str] | None = None,
    client_name: str = "MCP Inspector",
) -> OrchidMCPGatewayClient:
    return OrchidMCPGatewayClient(
        client_id=client_id,
        redirect_uris=redirect_uris or ["http://localhost:8765/callback"],
        grant_types=grant_types or ["authorization_code", "refresh_token"],
        response_types=response_types or ["code"],
        client_name=client_name,
    )


def _auth_code(
    code: str = "authcode-xyz",
    *,
    upstream_state: str = "ust-123",
    client_id: str = "cli-abc",
    scopes: list[str] | None = None,
    identity: dict | None = None,
) -> OrchidMCPGatewayAuthCode:
    return OrchidMCPGatewayAuthCode(
        code=code,
        client_id=client_id,
        redirect_uri="http://localhost:8765/callback",
        code_challenge="challenge-abc",
        code_challenge_method="S256",
        upstream_state=upstream_state,
        upstream_code_verifier="verifier-def",
        scopes=scopes or ["mcp.read"],
        client_state="client-echo-state",
        identity=identity,
    )


def _gateway_token(
    access_token: str = "at-1",
    *,
    refresh_token: str = "rt-1",
    subject: str = "u-42",
    identity: dict | None = None,
    scopes: list[str] | None = None,
    expires_at: float | None = None,
) -> OrchidMCPGatewayToken:
    return OrchidMCPGatewayToken(
        access_token=access_token,
        refresh_token=refresh_token,
        client_id="cli-abc",
        subject=subject,
        identity=identity or {"sub": subject, "email": "a@b.c"},
        scopes=scopes or ["mcp.read"],
        expires_at=time.time() + 3600 if expires_at is None else expires_at,
    )


class TestGatewayClientStore:
    async def test_get_returns_none_when_empty(self, gateway_store):
        assert await gateway_store.get("missing") is None

    async def test_register_and_get_round_trip(self, gateway_store):
        await gateway_store.register(_client())
        loaded = await gateway_store.get("cli-abc")
        assert loaded is not None
        assert loaded.client_id == "cli-abc"
        assert loaded.client_name == "MCP Inspector"
        assert loaded.redirect_uris == ["http://localhost:8765/callback"]
        assert loaded.grant_types == ["authorization_code", "refresh_token"]
        assert loaded.response_types == ["code"]
        assert loaded.token_endpoint_auth_method == "none"
        assert loaded.created_at > 0

    async def test_register_replaces_existing_record(self, gateway_store):
        await gateway_store.register(_client(client_name="first"))
        await gateway_store.register(_client(client_name="second", redirect_uris=["http://other"]))

        loaded = await gateway_store.get("cli-abc")
        assert loaded is not None
        assert loaded.client_name == "second"
        assert loaded.redirect_uris == ["http://other"]

    async def test_different_clients_isolated(self, gateway_store):
        await gateway_store.register(_client(client_id="alice", client_name="alice-client"))
        await gateway_store.register(_client(client_id="bob", client_name="bob-client"))

        alice = await gateway_store.get("alice")
        bob = await gateway_store.get("bob")
        assert alice is not None and alice.client_name == "alice-client"
        assert bob is not None and bob.client_name == "bob-client"


class TestGatewayAuthCodeStore:
    async def test_lookup_returns_none_when_empty(self, gateway_store):
        assert await gateway_store.get_by_upstream_state("missing") is None

    async def test_put_and_lookup_by_upstream_state(self, gateway_store):
        await gateway_store.put(_auth_code())
        loaded = await gateway_store.get_by_upstream_state("ust-123")
        assert loaded is not None
        assert loaded.code == "authcode-xyz"
        assert loaded.scopes == ["mcp.read"]
        assert loaded.client_state == "client-echo-state"
        assert loaded.identity is None
        assert loaded.idp_access_token == ""
        assert loaded.idp_refresh_token == ""
        assert loaded.idp_expires_at == 0.0

    async def test_update_patches_only_specified_fields(self, gateway_store):
        await gateway_store.put(_auth_code())
        await gateway_store.update(
            "authcode-xyz",
            idp_access_token="at-v1",
            idp_refresh_token="rt-v1",
            idp_expires_at=time.time() + 600,
        )
        await gateway_store.update("authcode-xyz", identity={"sub": "u-42", "email": "a@b.c"})

        loaded = await gateway_store.get_by_upstream_state("ust-123")
        assert loaded is not None
        assert loaded.identity == {"sub": "u-42", "email": "a@b.c"}
        assert loaded.idp_access_token == "at-v1"
        assert loaded.idp_refresh_token == "rt-v1"
        assert loaded.idp_expires_at > 0.0

    async def test_update_noop_when_nothing_specified(self, gateway_store):
        await gateway_store.put(_auth_code(identity={"sub": "u-1"}))
        await gateway_store.update("authcode-xyz")  # all-None defaults

        loaded = await gateway_store.get_by_upstream_state("ust-123")
        assert loaded is not None
        assert loaded.identity == {"sub": "u-1"}

    async def test_consume_returns_row_then_deletes(self, gateway_store):
        await gateway_store.put(_auth_code(identity={"sub": "u-1"}))
        first = await gateway_store.consume("authcode-xyz")
        assert first is not None
        assert first.code == "authcode-xyz"
        assert first.identity == {"sub": "u-1"}

        assert await gateway_store.consume("authcode-xyz") is None

    async def test_consume_returns_none_when_missing(self, gateway_store):
        assert await gateway_store.consume("never-seen") is None

    async def test_identity_survives_json_round_trip(self, gateway_store):
        payload = {
            "sub": "u-42",
            "email": "a@b.c",
            "nested": {"platform": {"domain": "acme.example.com", "roles": [1, 2, 3]}},
        }
        await gateway_store.put(_auth_code(identity=payload))
        loaded = await gateway_store.get_by_upstream_state("ust-123")
        assert loaded is not None
        assert loaded.identity == payload


class TestGatewayTokenStore:
    async def test_lookup_returns_none_when_empty(self, gateway_store):
        assert await gateway_store.get_by_access_token("missing") is None
        assert await gateway_store.get_by_refresh_token("missing") is None

    async def test_issue_and_lookup_by_access_token(self, gateway_store):
        await gateway_store.issue(_gateway_token())
        loaded = await gateway_store.get_by_access_token("at-1")
        assert loaded is not None
        assert loaded.refresh_token == "rt-1"
        assert loaded.subject == "u-42"
        assert loaded.identity == {"sub": "u-42", "email": "a@b.c"}
        assert loaded.scopes == ["mcp.read"]

    async def test_issue_and_lookup_by_refresh_token(self, gateway_store):
        await gateway_store.issue(_gateway_token())
        loaded = await gateway_store.get_by_refresh_token("rt-1")
        assert loaded is not None
        assert loaded.access_token == "at-1"

    async def test_expired_access_token_returns_none(self, gateway_store):
        await gateway_store.issue(_gateway_token(expires_at=time.time() - 10))
        assert await gateway_store.get_by_access_token("at-1") is None

    async def test_expired_refresh_token_returns_none(self, gateway_store):
        await gateway_store.issue(_gateway_token(expires_at=time.time() - 10))
        assert await gateway_store.get_by_refresh_token("rt-1") is None

    async def test_revoke_returns_true_when_removed(self, gateway_store):
        await gateway_store.issue(_gateway_token())
        assert await gateway_store.revoke("at-1") is True
        assert await gateway_store.get_by_access_token("at-1") is None

    async def test_revoke_returns_false_when_missing(self, gateway_store):
        assert await gateway_store.revoke("never-seen") is False

    async def test_different_tokens_isolated(self, gateway_store):
        await gateway_store.issue(_gateway_token(access_token="at-a", refresh_token="rt-a", subject="alice"))
        await gateway_store.issue(_gateway_token(access_token="at-b", refresh_token="rt-b", subject="bob"))

        a = await gateway_store.get_by_access_token("at-a")
        b = await gateway_store.get_by_access_token("at-b")
        assert a is not None and a.subject == "alice"
        assert b is not None and b.subject == "bob"


class TestGatewayLifecycle:
    async def test_all_three_concerns_share_one_connection(self, gateway_store):
        await gateway_store.register(_client())
        await gateway_store.put(_auth_code())
        await gateway_store.issue(_gateway_token())

        assert await gateway_store.get("cli-abc") is not None
        assert await gateway_store.get_by_upstream_state("ust-123") is not None
        assert await gateway_store.get_by_access_token("at-1") is not None

    async def test_close_allows_reopen(self):
        s = OrchidSQLiteMCPGatewayStateStore(dsn=":memory:")
        await s.init_db()
        await s.close()
        await s.close()  # idempotent

    async def test_operations_after_close_raise(self):
        s = OrchidSQLiteMCPGatewayStateStore(dsn=":memory:")
        await s.init_db()
        await s.close()
        with pytest.raises(RuntimeError, match="init_db"):
            await s.get("cli-abc")
