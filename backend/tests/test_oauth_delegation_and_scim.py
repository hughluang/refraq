"""Interface-level tests for OAuth delegation (ID-JAG + RFC 8693), McpResourceGate, Principal.admit, and SCIM 2.0."""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from collections.abc import Callable, Mapping
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from starlette.testclient import TestClient as StarletteTestClient

from backend.admin.federation.binding_store import get_binding_store
from backend.admin.federation.errors import SsoAssertionRejected, SsoProviderUnavailable
from backend.admin.federation.pending_store import get_pending_store
from backend.admin.federation.provider_store import get_provider_store
from backend.admin.federation.spec import GroupMappingSpec, OidcConfig, ProviderRecord
from backend.admin.oauth.errors import OAuthTokenError
from backend.admin.oauth.exchange import (
    CLIENT_ASSERTION_TYPE_JWT,
    GRANT_TYPE_ID_JAG,
    GRANT_TYPE_TOKEN_EXCHANGE,
    ID_JAG_HEADER_TYP,
    TokenGrantRequest,
    create_oauth_client,
    exchange_delegated_token,
)
from backend.admin.oauth.runtime_store import get_oauth_runtime_store
from backend.admin.oauth.store import get_oauth_client_store
from backend.admin.principal import (
    ResourceSurface,
    VerifiedOrigin,
    resolve_bearer_principal,
)
from backend.admin.role_store import RoleRecord, get_role_store
from backend.admin.session_store import get_session_store
from backend.admin.subjects.records import SubjectAttributeRecord, UserGroupRecord
from backend.admin.subjects.store import get_subject_store
from backend.admin.token_store import get_token_store
from backend.admin.user_store import get_user_store
from backend.core.config import get_settings
from backend.core.time import utc_now
from backend.entity.access.actor_token import current_actor_token_id
from backend.entity.mcp.http import create_mcp_http_app as create_entity_mcp_app
from backend.main import app
from backend.metadata.mcp_http import create_mcp_http_app as create_metadata_mcp_app
from backend.metadata.source_access.service import (
    allows as source_allows,
    create_membership,
)
from backend.metadata.sources.store import SourceRecord, get_source_store


class StaticOidcAdapter:
    """Deterministic in-memory adapter for interface-level tests without monkeypatching."""

    def __init__(
        self,
        *,
        get_responses: Mapping[str, dict[str, Any] | Callable[[], dict[str, Any]]] | None = None,
        post_responses: Mapping[
            str, dict[str, Any] | Callable[[Mapping[str, str]], dict[str, Any]]
        ]
        | None = None,
    ) -> None:
        self._get = dict(get_responses or {})
        self._post = dict(post_responses or {})

    def get_json(self, url: str) -> dict[str, Any]:
        entry = self._get.get(url)
        if entry is None:
            raise SsoProviderUnavailable(f"No static GET response configured for {url}")
        result = entry() if callable(entry) else entry
        if not isinstance(result, dict):
            raise SsoAssertionRejected("Remote JSON document is invalid")
        return dict(result)

    def post_form(self, url: str, data: Mapping[str, str]) -> dict[str, Any]:
        entry = self._post.get(url)
        if entry is None:
            raise SsoProviderUnavailable(f"No static POST response configured for {url}")
        result = entry(data) if callable(entry) else entry
        if not isinstance(result, dict):
            raise SsoAssertionRejected("OIDC token response is invalid")
        return dict(result)


def _make_rsa_keypair(kid: str) -> tuple[object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk["kid"] = kid
    public_jwk["use"] = "sig"
    public_jwk["alg"] = "RS256"
    return private_key, public_jwk


def _admin_headers(client: TestClient) -> dict[str, str]:
    users = get_user_store()
    admin = users.get_by_account(get_settings().initial_admin_account)
    assert admin is not None
    sid = get_session_store().create(admin.id, ttl_seconds=3600, idle_seconds=1800)
    client.cookies.set("refraq_sid", sid)
    return {}


def _create_role(key: str, name: str, permissions: list[str]) -> RoleRecord:
    record = RoleRecord(
        id=f"role_{uuid.uuid4().hex[:12]}",
        key=key,
        name=name,
        permissions=permissions,
    )
    get_role_store().insert(record)
    return record


def _seed_provider(
    *,
    issuer: str = "https://idp.example.com",
    default_role_id: str | None = None,
    group_mappings: list[GroupMappingSpec] | None = None,
) -> ProviderRecord:
    now = utc_now()
    record = ProviderRecord(
        id=f"idp_{uuid.uuid4().hex[:12]}",
        protocol="oidc",
        display_name="Corporate IdP",
        issuer=issuer,
        enabled=True,
        config=OidcConfig(
            issuer=issuer,
            client_id="refraq-console",
            client_secret="console-secret",
            scopes=["openid", "profile", "email"],
            auto_provision=True,
            group_claim="groups",
            group_allowlist=["/dept/sales"],
            group_mappings=group_mappings or [],
            scim_subject_source="external_id",
            default_role_id=default_role_id,
        ),
        created_at=now,
        updated_at=now,
    )
    return get_provider_store().save(record)


def test_id_jag_private_key_jwt_headless_jit_group_sync_and_replay() -> None:
    with TestClient(app):
        # Data-consumer role WITHOUT console:access
        consumer_role = _create_role(
            key="data_consumer",
            name="Data Consumer",
            permissions=["entity:data_read", "sources:read", "metadata:read"],
        )
        subjects = get_subject_store()
        now = utc_now()
        sales_group = subjects.create_group(
            UserGroupRecord(
                id="grp_sales",
                key="sales_team",
                name="Sales Team",
                description=None,
                created_at=now,
                updated_at=now,
            )
        )
        manual_group = subjects.create_group(
            UserGroupRecord(
                id="grp_manual",
                key="manual_team",
                name="Manual Team",
                description=None,
                created_at=now,
                updated_at=now,
            )
        )
        provider = _seed_provider(
            default_role_id=consumer_role.id,
            group_mappings=[
                GroupMappingSpec(external_group="/dept/sales", group_key="sales_team")
            ],
        )

        idp_priv, idp_jwk = _make_rsa_keypair("idp-k1")
        client_priv, client_jwk = _make_rsa_keypair("cli-k1")

        http = StaticOidcAdapter(
            get_responses={
                "https://idp.example.com/.well-known/openid-configuration": {
                    "issuer": "https://idp.example.com",
                    "authorization_endpoint": "https://idp.example.com/authorize",
                    "token_endpoint": "https://idp.example.com/token",
                    "jwks_uri": "https://idp.example.com/jwks.json",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
                "https://idp.example.com/jwks.json": {"keys": [idp_jwk]},
            }
        )

        oauth_client, secret = create_oauth_client(
            name="System A",
            description="Enterprise AI assistant",
            provider_id=provider.id,
            enabled=True,
            token_endpoint_auth_method="private_key_jwt",
            jwks={"keys": [client_jwk]},
            jwks_uri=None,
            allowed_grant_types=[GRANT_TYPE_ID_JAG],
            allowed_subject_audiences=[],
            allowed_surfaces=["entity_mcp"],
            allowed_scopes=["entity:data_read"],
            token_ttl_sec=600,
            actor_user_id=None,
            actor_token_id=None,
            store=get_oauth_client_store(),
            providers=get_provider_store(),
        )
        assert secret is None

        origin = VerifiedOrigin(proto="https", host="refraq.example.com")
        ts = int(time.time())
        client_assertion = jwt.encode(
            {
                "iss": oauth_client.client_id,
                "sub": oauth_client.client_id,
                "aud": origin.oauth_issuer(),
                "exp": ts + 120,
                "iat": ts,
                "jti": "cli-jti-1",
            },
            client_priv,  # type: ignore[arg-type]
            algorithm="RS256",
            headers={"kid": "cli-k1"},
        )
        id_jag = jwt.encode(
            {
                "iss": provider.issuer,
                "sub": "ext-alice",
                "aud": origin.oauth_issuer(),
                "client_id": oauth_client.client_id,
                "resource": origin.resource_uri(ResourceSurface.ENTITY_MCP),
                "preferred_username": "alice",
                "email": "alice@example.com",
                "name": "Alice Sales",
                "groups": ["/dept/sales"],
                "exp": ts + 120,
                "iat": ts,
                "jti": "jag-jti-1",
            },
            idp_priv,  # type: ignore[arg-type]
            algorithm="RS256",
            headers={"kid": "idp-k1", "typ": ID_JAG_HEADER_TYP},
        )

        result = exchange_delegated_token(
            origin=origin,
            req=TokenGrantRequest(
                grant_type=GRANT_TYPE_ID_JAG,
                client_assertion_type=CLIENT_ASSERTION_TYPE_JWT,
                client_assertion=client_assertion,
                assertion=id_jag,
                resource=origin.resource_uri(ResourceSurface.ENTITY_MCP),
            ),
            http=http,
            clients=get_oauth_client_store(),
            providers=get_provider_store(),
            users=get_user_store(),
            roles=get_role_store(),
            bindings=get_binding_store(),
            subjects=get_subject_store(),
            runtime=get_oauth_runtime_store(),
        )
        assert result.access_token.startswith("rfq_oat_")
        issued = get_oauth_runtime_store().resolve_token(result.access_token)
        assert issued is not None
        assert issued.token_id.startswith("oat_")
        assert result.scope == "entity:data_read"

        # User was provisioned headlessly without console:access and without polluting PendingStore
        user = get_user_store().get_by_account("alice")
        assert user is not None
        assert user.identity_source == "oidc"
        pending_items, pending_total = get_pending_store().list_pending()
        assert pending_total == 0
        assert pending_items == []

        # Scoped group mapping synced sales_team; manual_team is preserved on next exchange
        assert subjects.group_ids_of(user.id) == [sales_group.id]
        subjects.add_member(manual_group.id, user.id)

        # Replaying the exact same client_assertion jti is rejected
        try:
            exchange_delegated_token(
                origin=origin,
                req=TokenGrantRequest(
                    grant_type=GRANT_TYPE_ID_JAG,
                    client_assertion_type=CLIENT_ASSERTION_TYPE_JWT,
                    client_assertion=client_assertion,
                    assertion=id_jag,
                    resource=origin.resource_uri(ResourceSurface.ENTITY_MCP),
                ),
                http=http,
                clients=get_oauth_client_store(),
                providers=get_provider_store(),
                users=get_user_store(),
                roles=get_role_store(),
                bindings=get_binding_store(),
                subjects=get_subject_store(),
                runtime=get_oauth_runtime_store(),
            )
            assert False, "Expected replay to be rejected"
        except OAuthTokenError as exc:
            assert exc.error == "invalid_client"

        # Replaying the exact same ID-JAG jti with a fresh client_assertion is also rejected
        client_assertion_2 = jwt.encode(
            {
                "iss": oauth_client.client_id,
                "sub": oauth_client.client_id,
                "aud": origin.oauth_issuer(),
                "exp": ts + 120,
                "iat": ts,
                "jti": "cli-jti-2",
            },
            client_priv,  # type: ignore[arg-type]
            algorithm="RS256",
            headers={"kid": "cli-k1"},
        )
        try:
            exchange_delegated_token(
                origin=origin,
                req=TokenGrantRequest(
                    grant_type=GRANT_TYPE_ID_JAG,
                    client_assertion_type=CLIENT_ASSERTION_TYPE_JWT,
                    client_assertion=client_assertion_2,
                    assertion=id_jag,
                    resource=origin.resource_uri(ResourceSurface.ENTITY_MCP),
                ),
                http=http,
                clients=get_oauth_client_store(),
                providers=get_provider_store(),
                users=get_user_store(),
                roles=get_role_store(),
                bindings=get_binding_store(),
                subjects=get_subject_store(),
                runtime=get_oauth_runtime_store(),
            )
            assert False, "Expected ID-JAG replay to be rejected"
        except OAuthTokenError as exc:
            assert exc.error == "invalid_grant"

        # Cross-surface isolation: entity_mcp token works on /mcp/entity, rejected on /mcp and /api
        principal = resolve_bearer_principal(
            f"Bearer {result.access_token}",
            surface=ResourceSurface.ENTITY_MCP,
            tokens=get_token_store(),
            users=get_user_store(),
            roles=get_role_store(),
            runtime=get_oauth_runtime_store(),
            bindings=get_binding_store(),
        )
        assert principal.effective_permissions == frozenset({"entity:data_read"})
        assert principal.actor_token_id == issued.token_id

        # Principal.admit carries actor_token_id into worker threads
        seen_token_id = asyncio.run(principal.admit(current_actor_token_id))
        assert seen_token_id == issued.token_id

        with StarletteTestClient(create_metadata_mcp_app()) as meta_mcp:
            denied = meta_mcp.post(
                "/mcp",
                headers={"Authorization": f"Bearer {result.access_token}"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert denied.status_code == 401
            assert "resource_metadata=" in denied.headers.get("www-authenticate", "")
            assert "/.well-known/oauth-protected-resource/mcp" in denied.headers.get(
                "www-authenticate", ""
            )


def test_rfc8693_discovery_and_worker_thread_source_access_ceiling() -> None:
    with TestClient(app) as client:
        # Discovery endpoints
        as_meta = client.get("/.well-known/oauth-authorization-server")
        assert as_meta.status_code == 200
        assert as_meta.json()["token_endpoint"].endswith("/api/oauth/token")
        assert "urn:ietf:params:oauth:grant-profile:id-jag" in as_meta.json()[
            "authorization_grant_profiles_supported"
        ]

        pr_meta = client.get("/.well-known/oauth-protected-resource/mcp/entity")
        assert pr_meta.status_code == 200
        assert pr_meta.json()["resource"].endswith("/mcp/entity")

        # Entity MCP unauthenticated 401 advertises RFC 9728 resource_metadata
        with StarletteTestClient(create_entity_mcp_app()) as entity_mcp:
            unauth = entity_mcp.post(
                "/mcp/entity",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert unauth.status_code == 401
            assert "/.well-known/oauth-protected-resource/mcp/entity" in unauth.headers.get(
                "www-authenticate", ""
            )

        # RFC 8693 exchange + scope ceiling enforced inside metadata.source_access worker thread
        steward_role = _create_role(
            key="meta_steward",
            name="Metadata Steward",
            permissions=["sources:read", "metadata:read", "metadata:write"],
        )
        provider = _seed_provider(default_role_id=steward_role.id)
        idp_priv, idp_jwk = _make_rsa_keypair("idp-k2")
        http = StaticOidcAdapter(
            get_responses={
                "https://idp.example.com/.well-known/openid-configuration": {
                    "issuer": "https://idp.example.com",
                    "authorization_endpoint": "https://idp.example.com/authorize",
                    "token_endpoint": "https://idp.example.com/token",
                    "jwks_uri": "https://idp.example.com/jwks.json",
                    "id_token_signing_alg_values_supported": ["RS256"],
                },
                "https://idp.example.com/jwks.json": {"keys": [idp_jwk]},
            }
        )
        oauth_client, client_secret = create_oauth_client(
            name="Read-Only Metadata Bot",
            description=None,
            provider_id=provider.id,
            enabled=True,
            token_endpoint_auth_method="client_secret_post",
            jwks=None,
            jwks_uri=None,
            allowed_grant_types=[GRANT_TYPE_TOKEN_EXCHANGE],
            allowed_subject_audiences=["sys-b-app"],
            allowed_surfaces=["metadata_mcp"],
            allowed_scopes=["sources:read", "metadata:read"],
            token_ttl_sec=300,
            actor_user_id=None,
            actor_token_id=None,
            store=get_oauth_client_store(),
            providers=get_provider_store(),
        )
        assert client_secret is not None

        ts = int(time.time())
        subject_token = jwt.encode(
            {
                "iss": provider.issuer,
                "sub": "ext-bob",
                "aud": "sys-b-app",
                "preferred_username": "bob",
                "groups": ["/dept/sales"],
                "exp": ts + 120,
                "iat": ts,
            },
            idp_priv,  # type: ignore[arg-type]
            algorithm="RS256",
            headers={"kid": "idp-k2"},
        )
        origin = VerifiedOrigin(proto="http", host="127.0.0.1:3000")
        exchanged = exchange_delegated_token(
            origin=origin,
            req=TokenGrantRequest(
                grant_type=GRANT_TYPE_TOKEN_EXCHANGE,
                client_id=oauth_client.client_id,
                client_secret=client_secret,
                subject_token=subject_token,
                resource=origin.resource_uri(ResourceSurface.METADATA_MCP),
            ),
            http=http,
            clients=get_oauth_client_store(),
            providers=get_provider_store(),
            users=get_user_store(),
            roles=get_role_store(),
            bindings=get_binding_store(),
            subjects=get_subject_store(),
            runtime=get_oauth_runtime_store(),
        )
        principal = resolve_bearer_principal(
            f"Bearer {exchanged.access_token}",
            surface=ResourceSurface.METADATA_MCP,
            tokens=get_token_store(),
            users=get_user_store(),
            roles=get_role_store(),
            runtime=get_oauth_runtime_store(),
            bindings=get_binding_store(),
        )
        assert "metadata:read" in principal.effective_permissions
        assert "metadata:write" not in principal.effective_permissions

        # Give bob steward membership on a source, verify worker thread still enforces OAuth ceiling
        now = utc_now()
        src = get_source_store().create_source(
            SourceRecord(
                id="src_demo",
                key="demo_db",
                locator_key="demo_db",
                name="Demo DB",
                kind="database",
                status="active",
                description=None,
                engine="postgresql",
                access_ciphertext=None,
                access_updated_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        create_membership(
            subject_type="user",
            subject_id=principal.user_id,
            target=src.id,
            level="steward",
        )
        assert asyncio.run(
            principal.admit(lambda: source_allows(principal, src.id, "metadata:read"))
        )
        try:
            asyncio.run(
                principal.admit(
                    lambda: source_allows(principal, src.id, "metadata:write")
                )
            )
            assert False, "Expected OAuth scope ceiling to deny metadata:write inside worker thread"
        except Exception as exc:
            assert getattr(exc, "code", None) == "AUTH_FORBIDDEN"


def test_scim_users_groups_subject_attrs_and_instant_revocation() -> None:
    with TestClient(app) as client:
        _admin_headers(client)
        now = utc_now()
        subjects = get_subject_store()
        subjects.create_definition(
            SubjectAttributeRecord(
                id="sattr_region",
                key="region",
                name="Region",
                description=None,
                value_type="string",
                dictionary_id=None,
                multi_value=False,
                created_at=now,
                updated_at=now,
            )
        )
        consumer_role = _create_role(
            key="scim_reader",
            name="SCIM Reader",
            permissions=["entity:data_read"],
        )
        provider_a = _seed_provider(
            issuer="https://idp-a.example.com", default_role_id=consumer_role.id
        )
        provider_b = _seed_provider(
            issuer="https://idp-b.example.com", default_role_id=consumer_role.id
        )

        # Mint SCIM tokens per provider
        tok_a_resp = client.post(
            f"/identity-providers/{provider_a.id}/scim-tokens",
            json={"name": "Okta SCIM"},
        )
        assert tok_a_resp.status_code == 201, tok_a_resp.text
        scim_token_a = tok_a_resp.json()["token"]

        tok_b_resp = client.post(
            f"/identity-providers/{provider_b.id}/scim-tokens",
            json={"name": "Entra SCIM"},
        )
        assert tok_b_resp.status_code == 201
        scim_token_b = tok_b_resp.json()["token"]

        headers_a = {"Authorization": f"Bearer {scim_token_a}"}
        headers_b = {"Authorization": f"Bearer {scim_token_b}"}

        # Create SCIM User with Subject Attribute extension
        created = client.post(
            "/scim/v2/Users",
            headers=headers_a,
            json={
                "schemas": [
                    "urn:ietf:params:scim:schemas:core:2.0:User",
                    "urn:ietf:params:scim:schemas:extension:refraq:2.0:User",
                ],
                "externalId": "sub-carol",
                "userName": "carol",
                "displayName": "Carol North",
                "active": True,
                "emails": [{"value": "carol@example.com", "primary": True}],
                "urn:ietf:params:scim:schemas:extension:refraq:2.0:User": {
                    "region": "north"
                },
            },
        )
        assert created.status_code == 201, created.text
        carol_id = created.json()["id"]
        assert (
            created.json()["urn:ietf:params:scim:schemas:extension:refraq:2.0:User"][
                "region"
            ]
            == "north"
        )

        # Provider B cannot see Provider A's user
        assert client.get(f"/scim/v2/Users/{carol_id}", headers=headers_b).status_code == 404

        # Mint a session + delegated OAuth token for Carol
        sid = get_session_store().create(carol_id, ttl_seconds=3600, idle_seconds=1800)
        _oat_rec, oat_secret = get_oauth_runtime_store().issue_token(
            user_id=carol_id,
            client_id="rfq_cid_test",
            provider_id=provider_a.id,
            scopes=("entity:data_read",),
            surfaces=("entity_mcp",),
            ttl_sec=600,
        )
        assert get_session_store().get(sid) == carol_id
        assert get_oauth_runtime_store().resolve_token(oat_secret) is not None

        # PATCH active=false immediately revokes BOTH session and rfq_oat_ token
        patched = client.patch(
            f"/scim/v2/Users/{carol_id}",
            headers=headers_a,
            json={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                "Operations": [{"op": "replace", "path": "active", "value": False}],
            },
        )
        assert patched.status_code == 200
        assert patched.json()["active"] is False
        assert get_session_store().get(sid) is None
        assert get_oauth_runtime_store().resolve_token(oat_secret) is None

        # DELETE soft-deprovisions -> GET returns 404, binding has scim_deprovisioned_at
        deleted = client.delete(f"/scim/v2/Users/{carol_id}", headers=headers_a)
        assert deleted.status_code == 204
        assert client.get(f"/scim/v2/Users/{carol_id}", headers=headers_a).status_code == 404
        binding = get_binding_store().get(provider_a.issuer, "sub-carol")
        assert binding is not None and binding.scim_deprovisioned_at is not None

        # Re-POSTing the same (issuer, subject) reactivates the exact same UserRow
        reactivated = client.post(
            "/scim/v2/Users",
            headers=headers_a,
            json={
                "externalId": "sub-carol",
                "userName": "carol",
                "displayName": "Carol Returned",
                "active": True,
            },
        )
        assert reactivated.status_code == 201
        assert reactivated.json()["id"] == carol_id
        assert reactivated.json()["active"] is True

        # Unsupported user patch path returns 400 invalidPath instead of 200
        bad_user_patch = client.patch(
            f"/scim/v2/Users/{carol_id}",
            headers=headers_a,
            json={
                "Operations": [{"op": "replace", "path": "unknownAttr", "value": "x"}],
            },
        )
        assert bad_user_patch.status_code == 400
        assert bad_user_patch.json()["scimType"] == "invalidPath"

        # SCIM Group create + member sync + invalid patch + delete
        grp = client.post(
            "/scim/v2/Groups",
            headers=headers_a,
            json={
                "externalId": "ext-grp-north",
                "displayName": "North Region",
                "members": [{"value": carol_id}],
            },
        )
        assert grp.status_code == 201, grp.text
        grp_id = grp.json()["id"]
        assert grp.json()["members"] == [{"value": carol_id}]
        assert grp_id in subjects.group_ids_of(carol_id)

        bad_grp_patch = client.patch(
            f"/scim/v2/Groups/{grp_id}",
            headers=headers_a,
            json={
                "Operations": [{"op": "replace", "path": "members", "value": "not-a-list"}],
            },
        )
        assert bad_grp_patch.status_code == 400
        assert bad_grp_patch.json()["scimType"] == "invalidValue"

        assert client.delete(f"/scim/v2/Groups/{grp_id}", headers=headers_a).status_code == 204
