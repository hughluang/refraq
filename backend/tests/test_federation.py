"""OIDC federation tests for docs/business-identity-providers.md."""

from __future__ import annotations

import base64
import json
import os
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

os.environ.setdefault("REFRAQ_SKIP_SEED", "1")

from backend.admin.roles import seed_roles  # noqa: E402
from backend.admin.role_store import MemoryRoleStore, get_role_store, reset_role_store  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.audit_store import get_audit_store  # noqa: E402
from backend.admin.federation.errors import SsoAssertionRejected  # noqa: E402
from backend.admin.session_store import (  # noqa: E402
    MemorySessionStore,
    get_session_store,
    reset_session_store,
)
from backend.admin.system_parameters import resolve_int, set_parameter  # noqa: E402
from backend.admin.user_store import MemoryUserStore, get_user_store, reset_user_store  # noqa: E402
from backend.admin.federation.protocols.oidc.jwks import signing_key  # noqa: E402
from backend.admin.federation.service import safe_from  # noqa: E402
from backend.admin.federation.spec import OidcConfig  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.main import app  # noqa: E402
from backend.tests.problem import assert_problem  # noqa: E402

ISSUER = "https://idp.example"
KID = "test-key"


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", ISSUER)
            raise httpx.HTTPStatusError(
                "error",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self) -> Any:
        return self._payload


@pytest.fixture
def rsa_pair() -> tuple[Any, dict[str, Any]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = KID
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return key, jwk


@pytest.fixture
def store_bundle():
    reset_user_store()
    reset_role_store()
    reset_session_store()
    roles = MemoryRoleStore()
    seed_roles(roles)
    users = MemoryUserStore()
    super_admin = roles.get_by_key("super_admin")
    operator = roles.get_by_key("operator")
    assert super_admin is not None and operator is not None
    users.create_user(
        account="root",
        display_name="Root",
        password_hash=hash_password("s3cret"),
        role_id=super_admin.id,
    )
    users.create_user(
        account="op",
        display_name="Operator",
        password_hash=hash_password("op-pass"),
        role_id=operator.id,
    )
    sessions = MemorySessionStore()
    yield users, roles, sessions
    app.dependency_overrides.clear()
    reset_user_store()
    reset_role_store()
    reset_session_store()


@pytest.fixture
def client(store_bundle):
    users, roles, sessions = store_bundle
    app.dependency_overrides[get_user_store] = lambda: users
    app.dependency_overrides[get_role_store] = lambda: roles
    app.dependency_overrides[get_session_store] = lambda: sessions
    with TestClient(app) as test_client:
        yield test_client


def _login_root(client: TestClient) -> None:
    assert client.post("/auth/login", json={"account": "root", "password": "s3cret"}).status_code == 200


def _operator_id(roles: MemoryRoleStore) -> str:
    role = roles.get_by_key("operator")
    assert role is not None
    return role.id


def _provider_body(default_role_id: str, **overrides: Any) -> dict[str, Any]:
    body = {
        "protocol": "oidc",
        "display_name": "Corporate",
        "issuer": ISSUER,
        "client_id": "refraq",
        "client_secret": "s3cret",
        "auto_provision": True,
        "group_claim": "groups",
        "group_allowlist": ["/dept/analytics"],
        "default_role_id": default_role_id,
        "scopes": ["openid", "profile", "email"],
    }
    body.update(overrides)
    return body


def _install_idp(
    monkeypatch: pytest.MonkeyPatch,
    jwk: dict[str, Any],
    token_holder: dict[str, str],
    *,
    discovery_issuer: str = ISSUER,
    iss_param_supported: bool = True,
    signing_algs: Any = ["RS256"],
) -> None:
    def fake_get(url: str, timeout: float | None = None) -> FakeResponse:
        if url.endswith("/.well-known/openid-configuration"):
            payload: dict[str, Any] = {
                "issuer": discovery_issuer,
                "authorization_endpoint": f"{ISSUER}/auth",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
                "authorization_response_iss_parameter_supported": iss_param_supported,
            }
            if signing_algs is not None:
                payload["id_token_signing_alg_values_supported"] = signing_algs
            return FakeResponse(payload)
        if url.endswith("/jwks"):
            return FakeResponse({"keys": [jwk]})
        raise AssertionError(url)

    def fake_post(url: str, data: dict[str, str] | None = None, timeout: float | None = None) -> FakeResponse:
        assert url == f"{ISSUER}/token"
        return FakeResponse({"id_token": token_holder["id_token"]})

    monkeypatch.setattr("backend.admin.federation.protocols.oidc.discovery.httpx.get", fake_get)
    monkeypatch.setattr("backend.admin.federation.protocols.oidc.jwks.httpx.get", fake_get)
    monkeypatch.setattr("backend.admin.federation.protocols.oidc.adapter.httpx.post", fake_post)


def _mint(
    private_key: Any,
    *,
    nonce: str,
    sub: str = "user-1",
    groups: list[str] | None = ["/dept/analytics"],
    extra: dict[str, Any] | None = None,
    preferred_username: str = "alice",
) -> str:
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": sub,
        "aud": "refraq",
        "exp": utc_now().timestamp() + 300,
        "iat": utc_now().timestamp(),
        "nonce": nonce,
        "email": "alice@example.com",
        "name": "Alice",
        "preferred_username": preferred_username,
    }
    if groups is not None:
        claims["groups"] = groups
    if extra:
        claims.update(extra)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KID})


def _start(client: TestClient, provider_id: str) -> tuple[str, str]:
    response = client.get(
        f"/auth/sso/{provider_id}/start",
        params={"from": "/console"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    query = parse_qs(urlparse(location).query)
    return query["state"][0], query["nonce"][0]


def _callback(
    client: TestClient, provider_id: str, *, state: str, iss: str | None = ISSUER
) -> httpx.Response:
    params: dict[str, str] = {"code": "auth-code", "state": state}
    if iss is not None:
        params["iss"] = iss
    return client.get(
        f"/auth/sso/{provider_id}/callback",
        params=params,
        follow_redirects=False,
    )


def test_public_providers_omit_secrets(client: TestClient, store_bundle) -> None:
    _login_root(client)
    _, roles, _ = store_bundle
    created = client.post("/identity-providers", json=_provider_body(_operator_id(roles)))
    assert created.status_code == 200
    client.cookies.clear()
    listed = client.get("/auth/providers")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["display_name"] == "Corporate"
    assert item["protocol"] == "oidc"
    assert "client_secret" not in item
    assert "group_allowlist" not in item


def test_default_role_cannot_include_granting_permissions(
    client: TestClient, store_bundle
) -> None:
    _login_root(client)
    _, roles, _ = store_bundle
    super_admin = roles.get_by_key("super_admin")
    assert super_admin is not None
    response = client.post(
        "/identity-providers", json=_provider_body(super_admin.id)
    )
    assert_problem(response, status=409, code="IDENTITY_PROVIDER_DEFAULT_ROLE_FORBIDDEN")


def test_role_update_rejected_when_used_as_default(client: TestClient, store_bundle) -> None:
    _login_root(client)
    _, roles, _ = store_bundle
    created = client.post("/identity-providers", json=_provider_body(_operator_id(roles)))
    assert created.status_code == 200
    operator = roles.get_by_key("operator")
    assert operator is not None
    patched = client.patch(
        f"/roles/{operator.id}",
        json={"permissions": ["console:access", "dashboard:read", "users:write"]},
    )
    assert_problem(patched, status=409, code="IDENTITY_PROVIDER_DEFAULT_ROLE_FORBIDDEN")


def test_duplicate_issuer_rejected(client: TestClient, store_bundle) -> None:
    _login_root(client)
    _, roles, _ = store_bundle
    body = _provider_body(_operator_id(roles))
    assert client.post("/identity-providers", json=body).status_code == 200
    again = client.post(
        "/identity-providers", json={**body, "display_name": "Other"}
    )
    assert_problem(again, status=409, code="IDENTITY_PROVIDER_ISSUER_DUPLICATE")


def test_auto_provision_creates_user_and_session(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    users, roles, _sessions = store_bundle
    created = client.post("/identity-providers", json=_provider_body(_operator_id(roles)))
    provider_id = created.json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce)
    response = _callback(client, provider_id, state=state)
    assert response.status_code == 302
    assert response.headers["location"] == "/console"
    assert "refraq_sid" in response.cookies
    current = client.get("/auth/me")
    assert current.status_code == 200
    assert current.json()["user"]["identity_source"] == "oidc"
    alice = users.get_by_account("alice")
    assert alice is not None
    assert alice.identity_source == "oidc"
    assert alice.password_hash is None


def test_auto_provision_requires_console_access_default_role(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    users, _roles, _sessions = store_bundle
    role = client.post(
        "/roles",
        json={
            "key": "no_console",
            "name": "No Console",
            "permissions": ["dashboard:read"],
        },
    )
    assert role.status_code == 201
    provider_id = client.post(
        "/identity-providers", json=_provider_body(role.json()["role"]["id"])
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce)
    response = _callback(client, provider_id, state=state)
    assert response.status_code == 302
    assert "AUTH_CONSOLE_ACCESS_REQUIRED" in response.headers["location"]
    assert "refraq_sid" not in response.cookies
    assert users.get_by_account("alice") is None


def test_group_missing_and_overflow_queue_same_public_error(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()

    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce, sub="missing-user", groups=None)
    missing = _callback(client, provider_id, state=state)
    assert missing.status_code == 302
    assert "AUTH_SSO_NOT_ADMITTED" in missing.headers["location"]

    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(
        private_key,
        nonce=nonce,
        sub="overflow-user",
        groups=None,
        extra={"hasgroups": True},
    )
    overflow = _callback(client, provider_id, state=state)
    assert overflow.status_code == 302
    assert "AUTH_SSO_NOT_ADMITTED" in overflow.headers["location"]

    _login_root(client)
    pending = client.get("/users/pending-federated-identities")
    assert pending.status_code == 200
    reasons = {item["admission_reason"] for item in pending.json()["items"]}
    assert reasons == {"group_missing", "group_overflow"}


def test_account_collision_queues_without_binding(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    users, roles, _ = store_bundle
    _login_root(client)
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce, preferred_username="root")
    response = _callback(client, provider_id, state=state)
    assert "AUTH_SSO_NOT_ADMITTED" in response.headers["location"]
    root = users.get_by_account("root")
    assert root is not None
    assert root.identity_source == "local"
    _login_root(client)
    pending = client.get("/users/pending-federated-identities").json()["items"]
    assert pending[0]["admission_reason"] == "account_collision"


def test_every_login_group_check_does_not_queue(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    users, roles, _ = store_bundle
    _login_root(client)
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce, sub="user-bound")
    assert "refraq_sid" in _callback(client, provider_id, state=state).cookies
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(
        private_key, nonce=nonce, sub="user-bound", groups=["/other"]
    )
    denied = _callback(client, provider_id, state=state)
    assert "AUTH_SSO_NOT_ADMITTED" in denied.headers["location"]
    _login_root(client)
    pending = client.get("/users/pending-federated-identities").json()
    assert pending["total"] == 0
    alice = users.get_by_account("alice")
    assert alice is not None and alice.status == "active"


def test_nonce_and_iss_mismatch_rejected(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, _nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce="wrong-nonce")
    bad_nonce = _callback(client, provider_id, state=state)
    assert "AUTH_SSO_ASSERTION_REJECTED" in bad_nonce.headers["location"]
    events, _ = get_audit_store().list_events(action="sso_reject")
    assert any(item.detail.get("reason") == "assertion_rejected" for item in events)
    dumped = json.dumps([item.detail for item in events])
    assert "auth-code" not in dumped
    assert "id_token" not in dumped

    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce)
    bad_iss = _callback(client, provider_id, state=state, iss="https://other.example")
    assert "AUTH_SSO_ASSERTION_REJECTED" in bad_iss.headers["location"]


def test_handoff_mismatch(client: TestClient, store_bundle, rsa_pair, monkeypatch) -> None:
    _login_root(client)
    _, roles, _ = store_bundle
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": "x"}
    _install_idp(monkeypatch, jwk, holder)
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    missing = client.get(
        f"/auth/sso/{provider_id}/callback",
        params={"code": "x", "state": "nope"},
        follow_redirects=False,
    )
    assert "AUTH_SSO_HANDOFF_INVALID" in missing.headers["location"]


def test_expired_handoff_is_rejected(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    _login_root(client)
    _, roles, _ = store_bundle
    _private_key, jwk = rsa_pair
    holder = {"id_token": "unused"}
    _install_idp(monkeypatch, jwk, holder)
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, _nonce = _start(client, provider_id)
    monkeypatch.setattr(
        "backend.admin.federation.handoff_store.time.time",
        lambda: utc_now().timestamp() + 1_000,
    )

    expired = _callback(client, provider_id, state=state)

    assert "AUTH_SSO_HANDOFF_INVALID" in expired.headers["location"]


def test_consumed_handoff_is_rejected(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce)
    assert "refraq_sid" in _callback(client, provider_id, state=state).cookies
    client.cookies.set("refraq_sso", state)

    consumed = _callback(client, provider_id, state=state)

    assert "AUTH_SSO_HANDOFF_INVALID" in consumed.headers["location"]


@pytest.mark.parametrize(
    "value",
    [
        "//evil.example",
        "https://evil.example",
        "/\\evil.example",
        "/safe\\evil",
        "/safe\x00evil",
        "/%00evil",
        "/%2f%2fevil.example",
    ],
)
def test_safe_from_rejects_unsafe_return_paths(value: str) -> None:
    assert safe_from(value) == "/console"


def test_jwks_unknown_kid_respects_cooldown_then_refreshes(
    rsa_pair, monkeypatch
) -> None:
    _private_key, jwk = rsa_pair
    calls = 0
    clock = [100.0]

    def fake_get(url: str, timeout: float | None = None) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls < 3:
            return FakeResponse({"keys": [jwk]})
        rotated = dict(jwk)
        rotated["kid"] = "rotated-key"
        return FakeResponse({"keys": [rotated]})

    monkeypatch.setattr(
        "backend.admin.federation.protocols.oidc.jwks.httpx.get", fake_get
    )
    monkeypatch.setattr(
        "backend.admin.federation.protocols.oidc.jwks.time.monotonic",
        lambda: clock[0],
    )

    with pytest.raises(SsoAssertionRejected, match="signing key is unknown"):
        signing_key(f"{ISSUER}/jwks", "rotated-key", "RS256")
    assert calls == 2
    with pytest.raises(SsoAssertionRejected, match="signing key is unknown"):
        signing_key(f"{ISSUER}/jwks", "rotated-key", "RS256")
    assert calls == 2

    clock[0] = 131.0
    key = signing_key(f"{ISSUER}/jwks", "rotated-key", "RS256")

    assert key is not None
    assert calls == 3


def test_oidc_user_password_login_hides_source(client: TestClient, store_bundle) -> None:
    users, roles, _ = store_bundle
    operator = roles.get_by_key("operator")
    assert operator is not None
    users.create_user(
        account="alice",
        display_name="Alice",
        password_hash=None,
        role_id=operator.id,
        identity_source="oidc",
    )
    response = client.post("/auth/login", json={"account": "alice", "password": "s3cret"})
    assert_problem(response, status=401, code="AUTH_INVALID_CREDENTIALS")


def test_last_local_super_admin_cannot_be_claimed(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    users, roles, _ = store_bundle
    _login_root(client)
    provider_id = client.post(
        "/identity-providers",
        json=_provider_body(_operator_id(roles), auto_provision=False, group_allowlist=[]),
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce)
    assert "AUTH_SSO_NOT_ADMITTED" in _callback(client, provider_id, state=state).headers["location"]
    _login_root(client)
    pending_id = client.get("/users/pending-federated-identities").json()["items"][0]["id"]
    root = users.get_by_account("root")
    assert root is not None
    claimed = client.post(
        f"/users/pending-federated-identities/{pending_id}/claim",
        json={"user_id": root.id},
    )
    assert_problem(claimed, status=409, code="FEDERATION_LAST_LOCAL_SUPER_ADMIN")


def test_claim_create_and_unfederate(client: TestClient, store_bundle, rsa_pair, monkeypatch) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    users, roles, _ = store_bundle
    _login_root(client)
    provider_id = client.post(
        "/identity-providers",
        json=_provider_body(_operator_id(roles), auto_provision=False, group_allowlist=[]),
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce)
    _callback(client, provider_id, state=state)
    _login_root(client)
    pending_id = client.get("/users/pending-federated-identities").json()["items"][0]["id"]
    created = client.post(
        f"/users/pending-federated-identities/{pending_id}/claim",
        json={
            "create_user": {
                "account": "alice",
                "display_name": "Alice",
                "email": "alice@example.com",
                "role_id": _operator_id(roles),
            }
        },
    )
    assert created.status_code == 200
    user_id = created.json()["user"]["id"]
    assert created.json()["user"]["identity_source"] == "oidc"
    unfederated = client.post(
        f"/users/{user_id}/unfederate", json={"password": "new-pass"}
    )
    assert unfederated.status_code == 200
    assert unfederated.json()["user"]["identity_source"] == "local"
    record = users.get_by_id(user_id)
    assert record is not None and record.password_hash is not None


def test_pending_ttl_fixed_on_first_sight(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers",
        json=_provider_body(_operator_id(roles), auto_provision=False, group_allowlist=[]),
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce, sub="ttl-user")
    _callback(client, provider_id, state=state)
    _login_root(client)
    first = client.get("/users/pending-federated-identities").json()["items"][0]
    first_expiry = first["expires_at"]
    set_parameter("sso_pending_ttl_days", 30, actor_user_id=None)
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce, sub="ttl-user")
    _callback(client, provider_id, state=state)
    _login_root(client)
    second = client.get("/users/pending-federated-identities").json()["items"][0]
    assert second["expires_at"] == first_expiry
    assert second["attempt_count"] == 2
    assert resolve_int("sso_pending_ttl_days").value == 30


def test_auto_off_skips_group_check_for_bound_user(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    users, roles, _ = store_bundle
    _login_root(client)
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce, sub="user-bound")
    assert "refraq_sid" in _callback(client, provider_id, state=state).cookies
    _login_root(client)
    patched = client.patch(
        f"/identity-providers/{provider_id}", json={"auto_provision": False}
    )
    assert patched.status_code == 200
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(
        private_key, nonce=nonce, sub="user-bound", groups=["/other"]
    )
    allowed = _callback(client, provider_id, state=state)
    assert allowed.status_code == 302
    assert allowed.headers["location"] == "/console"
    assert "refraq_sid" in allowed.cookies
    alice = users.get_by_account("alice")
    assert alice is not None and alice.status == "active"


def test_delete_provider_optionally_disables_bound_users(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    users, roles, _ = store_bundle
    _login_root(client)
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce, sub="user-bound")
    assert "refraq_sid" in _callback(client, provider_id, state=state).cookies
    alice = users.get_by_account("alice")
    assert alice is not None
    _login_root(client)
    deleted = client.delete(
        f"/identity-providers/{provider_id}",
        params={"disable_bound_users": "true"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["bound_user_count"] == 1
    refreshed = users.get_by_id(alice.id)
    assert refreshed is not None and refreshed.status == "disabled"
    listed = client.get("/identity-providers")
    assert listed.json()["total"] == 0


def _unsigned_token(claims: dict[str, Any]) -> str:
    def segment(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("ascii")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f"{segment({'alg': 'none', 'typ': 'JWT'})}.{segment(claims)}."


def test_provider_spec_omits_attribute_mapping(client: TestClient) -> None:
    _login_root(client)
    spec = client.get("/identity-providers/spec")
    assert spec.status_code == 200
    properties = spec.json()["spec"]["properties"]
    assert "group_claim" in properties
    assert "attribute_mapping" not in properties
    assert "use_par" not in properties
    assert "use_request_object" not in properties
    assert "trust_mode" not in properties


def test_legacy_attribute_mapping_is_ignored_during_decryption_compatibility() -> None:
    config = OidcConfig.from_dict(
        {
            "issuer": ISSUER,
            "client_id": "refraq",
            "client_secret": "secret",
            "attribute_mapping": {"email": "legacy_mail"},
            "use_par": True,
            "use_request_object": True,
            "trust_mode": "federation",
        }
    )

    dumped = config.to_dict()
    assert "attribute_mapping" not in dumped
    assert "use_par" not in dumped
    assert "use_request_object" not in dumped
    assert "trust_mode" not in dumped


def test_invalid_provider_config_rejected(client: TestClient, store_bundle) -> None:
    _login_root(client)
    _, roles, _ = store_bundle
    role_id = _operator_id(roles)
    cases = [
        {"scopes": ["profile", "email"]},
        {"scopes": ["openid", "offline_access"]},
        {"issuer": "not-a-url"},
        {"issuer": "https://idp.example/trailing/"},
        {"group_allowlist": []},
    ]
    for overrides in cases:
        response = client.post("/identity-providers", json=_provider_body(role_id, **overrides))
        assert_problem(response, status=400, code="IDENTITY_PROVIDER_INVALID_CONFIG")
    missing_role = _provider_body(role_id)
    del missing_role["default_role_id"]
    response = client.post("/identity-providers", json=missing_role)
    assert_problem(response, status=400, code="IDENTITY_PROVIDER_INVALID_CONFIG")


def test_default_role_cannot_include_roles_write(client: TestClient) -> None:
    _login_root(client)
    created = client.post(
        "/roles",
        json={
            "key": "grantor",
            "name": "Grantor",
            "permissions": ["console:access", "dashboard:read", "roles:write"],
        },
    )
    assert created.status_code == 201
    response = client.post(
        "/identity-providers", json=_provider_body(created.json()["role"]["id"])
    )
    assert_problem(response, status=409, code="IDENTITY_PROVIDER_DEFAULT_ROLE_FORBIDDEN")


def test_default_role_cannot_include_identity_providers_write(
    client: TestClient,
) -> None:
    _login_root(client)
    created = client.post(
        "/roles",
        json={
            "key": "provider_grantor",
            "name": "Provider Grantor",
            "permissions": [
                "console:access",
                "dashboard:read",
                "identity_providers:write",
            ],
        },
    )
    assert created.status_code == 201

    response = client.post(
        "/identity-providers", json=_provider_body(created.json()["role"]["id"])
    )

    assert_problem(
        response,
        status=409,
        code="IDENTITY_PROVIDER_DEFAULT_ROLE_FORBIDDEN",
    )


def test_missing_provider_is_not_found(client: TestClient) -> None:
    _login_root(client)
    response = client.get("/identity-providers/idp_missing")
    assert_problem(response, status=404, code="IDENTITY_PROVIDER_NOT_FOUND")


def test_connectivity_returns_group_claim_not_pending_groups(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(
        private_key, nonce=nonce, sub="unbound-other", groups=["/other"]
    )
    queued = _callback(client, provider_id, state=state)
    assert "AUTH_SSO_NOT_ADMITTED" in queued.headers["location"]
    _login_root(client)
    pending = client.get("/users/pending-federated-identities").json()["items"]
    assert pending[0]["admission_reason"] == "group_not_allowed"
    assert pending[0]["groups"] == ["/other"]
    tested = client.post(f"/identity-providers/{provider_id}/test")
    assert tested.status_code == 200
    body = tested.json()
    assert body["group_claim"] == "groups"
    assert body["issuer"] == ISSUER
    assert "groups_sample" not in body


def test_claim_names_overflow_queues(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(
        private_key,
        nonce=nonce,
        sub="overflow-names",
        groups=None,
        extra={"_claim_names": {"groups": "src1"}},
    )
    response = _callback(client, provider_id, state=state)
    assert "AUTH_SSO_NOT_ADMITTED" in response.headers["location"]
    _login_root(client)
    pending = client.get("/users/pending-federated-identities").json()["items"]
    assert pending[0]["admission_reason"] == "group_overflow"


def test_disabled_provider_unavailable(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    patched = client.patch(f"/identity-providers/{provider_id}", json={"enabled": False})
    assert patched.status_code == 200
    client.cookies.clear()
    missing = client.get("/auth/sso/idp_missing/start", follow_redirects=False)
    assert "AUTH_SSO_PROVIDER_UNAVAILABLE" in missing.headers["location"]
    disabled = client.get(
        f"/auth/sso/{provider_id}/start",
        params={"from": "/console"},
        follow_redirects=False,
    )
    assert "AUTH_SSO_PROVIDER_UNAVAILABLE" in disabled.headers["location"]


def test_disable_provider_optionally_disables_bound_users(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    users, roles, _ = store_bundle
    _login_root(client)
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce, sub="user-bound")
    assert "refraq_sid" in _callback(client, provider_id, state=state).cookies
    alice = users.get_by_account("alice")
    assert alice is not None
    _login_root(client)
    kept = client.patch(f"/identity-providers/{provider_id}", json={"enabled": False})
    assert kept.status_code == 200
    still = users.get_by_id(alice.id)
    assert still is not None and still.status == "active"
    client.patch(f"/identity-providers/{provider_id}", json={"enabled": True})
    cascaded = client.patch(
        f"/identity-providers/{provider_id}",
        json={"enabled": False},
        params={"disable_bound_users": "true"},
    )
    assert cascaded.status_code == 200
    disabled = users.get_by_id(alice.id)
    assert disabled is not None and disabled.status == "disabled"
    listed = client.get("/identity-providers")
    assert listed.json()["items"][0]["enabled"] is False


def test_bad_signature_and_alg_none_rejected(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(other, nonce=nonce)
    bad_sig = _callback(client, provider_id, state=state)
    assert "AUTH_SSO_ASSERTION_REJECTED" in bad_sig.headers["location"]
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _unsigned_token(
        {
            "iss": ISSUER,
            "sub": "user-1",
            "aud": "refraq",
            "exp": utc_now().timestamp() + 300,
            "iat": utc_now().timestamp(),
            "nonce": nonce,
        }
    )
    none_alg = _callback(client, provider_id, state=state)
    assert "AUTH_SSO_ASSERTION_REJECTED" in none_alg.headers["location"]


def test_discovery_issuer_mismatch_rejected(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    _install_idp(monkeypatch, jwk, holder, discovery_issuer="https://evil.example")
    holder["id_token"] = _mint(private_key, nonce=nonce)
    mismatched = _callback(client, provider_id, state=state)
    assert "AUTH_SSO_ASSERTION_REJECTED" in mismatched.headers["location"]


def test_provider_test_rejects_discovery_issuer_mismatch(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    _jwk = rsa_pair[1]
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, _jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    _install_idp(monkeypatch, _jwk, holder, discovery_issuer="https://evil.example")
    response = client.post(f"/identity-providers/{provider_id}/test")
    assert_problem(response, status=401, code="AUTH_SSO_ASSERTION_REJECTED")


def test_start_rejects_discovery_issuer_mismatch(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    _jwk = rsa_pair[1]
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, _jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    _install_idp(monkeypatch, _jwk, holder, discovery_issuer="https://evil.example")
    started = client.get(
        f"/auth/sso/{provider_id}/start",
        params={"from": "/console"},
        follow_redirects=False,
    )
    assert "AUTH_SSO_ASSERTION_REJECTED" in started.headers["location"]
    events, _ = get_audit_store().list_events(action="sso_reject")
    assert any(item.detail.get("reason") == "assertion_rejected" for item in events)


def test_unsupported_or_invalid_signing_algs_rejected(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    _jwk = rsa_pair[1]
    holder: dict[str, str] = {"id_token": ""}
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    _install_idp(monkeypatch, _jwk, holder, signing_algs=["HS256"])
    unsupported = client.post(f"/identity-providers/{provider_id}/test")
    assert_problem(unsupported, status=401, code="AUTH_SSO_ASSERTION_REJECTED")
    _install_idp(monkeypatch, _jwk, holder, signing_algs="RS256")
    invalid = client.post(f"/identity-providers/{provider_id}/test")
    assert_problem(invalid, status=401, code="AUTH_SSO_ASSERTION_REJECTED")


def test_users_read_cannot_list_pending(client: TestClient, store_bundle) -> None:
    users, _roles, _ = store_bundle
    _login_root(client)
    created = client.post(
        "/roles",
        json={
            "key": "user_reader",
            "name": "User reader",
            "permissions": ["console:access", "dashboard:read", "users:read"],
        },
    )
    assert created.status_code == 201
    users.create_user(
        account="reader",
        display_name="Reader",
        password_hash=hash_password("reader-pass"),
        role_id=created.json()["role"]["id"],
    )
    client.cookies.clear()
    assert (
        client.post(
            "/auth/login", json={"account": "reader", "password": "reader-pass"}
        ).status_code
        == 200
    )
    listed = client.get("/users/pending-federated-identities")
    assert_problem(listed, status=403, code="AUTH_FORBIDDEN")


def test_claim_existing_user_already_bound(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    users, roles, _ = store_bundle
    _login_root(client)
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce, sub="user-alice")
    assert "refraq_sid" in _callback(client, provider_id, state=state).cookies
    alice = users.get_by_account("alice")
    assert alice is not None
    _login_root(client)
    client.patch(f"/identity-providers/{provider_id}", json={"auto_provision": False})
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(
        private_key, nonce=nonce, sub="user-bob", preferred_username="bob"
    )
    queued = _callback(client, provider_id, state=state)
    assert "AUTH_SSO_NOT_ADMITTED" in queued.headers["location"]
    _login_root(client)
    pending_id = client.get("/users/pending-federated-identities").json()["items"][0]["id"]
    claimed = client.post(
        f"/users/pending-federated-identities/{pending_id}/claim",
        json={"user_id": alice.id},
    )
    assert_problem(claimed, status=409, code="FEDERATION_ALREADY_BOUND")


def test_issuer_cannot_change_after_create(client: TestClient, store_bundle) -> None:
    _login_root(client)
    _, roles, _ = store_bundle
    created = client.post("/identity-providers", json=_provider_body(_operator_id(roles)))
    provider_id = created.json()["provider"]["id"]
    patched = client.patch(
        f"/identity-providers/{provider_id}",
        json={"issuer": "https://other.example"},
    )
    assert_problem(patched, status=409, code="IDENTITY_PROVIDER_ISSUER_IMMUTABLE")
    got = client.get(f"/identity-providers/{provider_id}")
    assert got.json()["provider"]["issuer"] == ISSUER
    same = client.patch(
        f"/identity-providers/{provider_id}",
        json={"issuer": ISSUER, "display_name": "Renamed"},
    )
    assert same.status_code == 200
    assert same.json()["provider"]["issuer"] == ISSUER
    assert same.json()["provider"]["display_name"] == "Renamed"


def test_callback_origin_uses_configured_host_not_request_host(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    response = client.get(
        f"/auth/sso/{provider_id}/start",
        params={"from": "/console"},
        headers={"Host": "evil.example", "x-forwarded-host": "evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["redirect_uri"] == [
        f"http://127.0.0.1:3000/api/auth/sso/{provider_id}/callback"
    ]


def test_unconfigured_origin_rejects_non_loopback_host(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    from backend.core.config import reset_settings_cache

    monkeypatch.setenv("REFRAQ_BROWSER_FACING_HOST", "")
    reset_settings_cache()
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    allowed = client.get(
        f"/auth/sso/{provider_id}/start",
        params={"from": "/console"},
        headers={
            "Host": "127.0.0.1:3000",
            "x-forwarded-host": "127.0.0.1:3000",
        },
        follow_redirects=False,
    )
    assert allowed.status_code == 302
    assert "AUTH_SSO_PROVIDER_UNAVAILABLE" not in allowed.headers["location"]
    rejected = client.get(
        f"/auth/sso/{provider_id}/start",
        params={"from": "/console"},
        headers={"Host": "evil.example", "x-forwarded-host": "evil.example"},
        follow_redirects=False,
    )
    assert "AUTH_SSO_PROVIDER_UNAVAILABLE" in rejected.headers["location"]
    events, _ = get_audit_store().list_events(action="sso_reject")
    assert any(item.detail.get("reason") == "callback_origin_invalid" for item in events)


def test_unexpected_callback_error_is_internal(
    client: TestClient, store_bundle, rsa_pair, monkeypatch
) -> None:
    private_key, jwk = rsa_pair
    holder: dict[str, str] = {"id_token": ""}
    _install_idp(monkeypatch, jwk, holder)
    _login_root(client)
    _, roles, _ = store_bundle
    provider_id = client.post(
        "/identity-providers", json=_provider_body(_operator_id(roles))
    ).json()["provider"]["id"]
    client.cookies.clear()
    state, nonce = _start(client, provider_id)
    holder["id_token"] = _mint(private_key, nonce=nonce)

    def _boom(**_kwargs: Any) -> None:
        raise RuntimeError("database is down")

    monkeypatch.setattr("backend.admin.federation.router.complete_sso", _boom)
    with TestClient(app, raise_server_exceptions=False) as raw:
        raw.cookies.set("refraq_sso", state)
        response = raw.get(
            f"/auth/sso/{provider_id}/callback",
            params={"code": "auth-code", "state": state, "iss": ISSUER},
            follow_redirects=False,
        )
    assert_problem(response, status=500, code="INTERNAL_ERROR")
    assert "database is down" not in response.text

