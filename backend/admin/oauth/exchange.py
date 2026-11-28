"""OAuth Client administration, dual-mode token delegation (ID-JAG + RFC 8693), and discovery."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

import jwt

from backend.admin.audit import persist_audit_event
from backend.admin.errors import AuthAccountDisabled
from backend.admin.federation.binding_store import BindingStore
from backend.admin.federation.errors import (
    ProviderNotFound,
    SsoAssertionRejected,
    SsoNotAdmitted,
    SsoProviderUnavailable,
)
from backend.admin.federation.http_port import OidcHttpPort
from backend.admin.federation.protocols.oidc.claims import assertion_from_claims
from backend.admin.federation.protocols.oidc.discovery import discover
from backend.admin.federation.protocols.oidc.jwks import (
    ALLOWED_ALGS,
    find_key_in_jwks,
    signing_key,
)
from backend.admin.federation.provider_store import ProviderStore
from backend.admin.federation.provisioning import admit_external_subject
from backend.admin.oauth.errors import (
    OAuthClientConfigInvalid,
    OAuthClientNotFound,
    OAuthClientScopeForbidden,
    OAuthClientSecretUnsupported,
    OAuthTokenError,
)
from backend.admin.oauth.runtime_store import OAuthRuntimeStore
from backend.admin.oauth.store import OAuthClientRecord, OAuthClientStore
from backend.admin.parameters import oauth_access_token_ttl_sec
from backend.admin.permissions import ALL_PERMISSIONS, GRANTING_PERMISSIONS
from backend.admin.principal import ResourceSurface, VerifiedOrigin
from backend.admin.role_store import RoleStore
from backend.admin.roles import effective_permissions
from backend.admin.subjects.store import SubjectStore
from backend.admin.user_store import UserStore
from backend.core.time import utc_now

GRANT_TYPE_ID_JAG = "urn:ietf:params:oauth:grant-type:jwt-bearer"
GRANT_TYPE_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
CLIENT_ASSERTION_TYPE_JWT = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
ID_JAG_HEADER_TYP = "oauth-id-jag+jwt"
ISSUED_TOKEN_TYPE_ACCESS = "urn:ietf:params:oauth:token-type:access_token"
CLIENT_SECRET_PREFIX = "rfq_cs_"

SUPPORTED_AUTH_METHODS: frozenset[str] = frozenset(
    {"private_key_jwt", "client_secret_basic", "client_secret_post"}
)
SUPPORTED_GRANT_TYPES: frozenset[str] = frozenset(
    {GRANT_TYPE_ID_JAG, GRANT_TYPE_TOKEN_EXCHANGE}
)
SUPPORTED_SURFACES: frozenset[str] = frozenset(s.value for s in ResourceSurface)
FORBIDDEN_DELEGATED_SCOPES: frozenset[str] = (
    GRANTING_PERMISSIONS | frozenset({"tokens:write", "console:access"})
)
_PRIVATE_JWK_FIELDS: frozenset[str] = frozenset(
    {"d", "p", "q", "dp", "dq", "qi", "oth", "k"}
)
_MAX_CLIENT_ASSERTION_TTL_SEC = 300
_MAX_JTI_TTL_SEC = 3600


def _hash_secret(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def _generate_client_secret() -> tuple[str, str, str]:
    plaintext = f"{CLIENT_SECRET_PREFIX}{secrets.token_urlsafe(32)}"
    return plaintext, plaintext[:14], _hash_secret(plaintext)


def _validate_jwks_public_only(jwks: dict[str, Any]) -> dict[str, Any]:
    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys:
        raise OAuthClientConfigInvalid("jwks must contain a non-empty 'keys' array")
    for item in keys:
        if not isinstance(item, dict):
            raise OAuthClientConfigInvalid("Each JWK entry must be a JSON object")
        if _PRIVATE_JWK_FIELDS.intersection(item.keys()):
            raise OAuthClientConfigInvalid("jwks must contain public keys only")
    return jwks


def _validate_url(url: str, *, field_name: str) -> str:
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OAuthClientConfigInvalid(f"{field_name} must be an absolute http(s) URL")
    return cleaned


def _validate_client_fields(
    *,
    name: str,
    auth_method: str,
    jwks: dict[str, Any] | None,
    jwks_uri: str | None,
    grant_types: list[str],
    subject_audiences: list[str],
    surfaces: list[str],
    scopes: list[str],
    token_ttl_sec: int | None,
) -> tuple[
    str,
    dict[str, Any] | None,
    str | None,
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise OAuthClientConfigInvalid("name is required")
    if auth_method not in SUPPORTED_AUTH_METHODS:
        raise OAuthClientConfigInvalid("Unsupported token_endpoint_auth_method")

    clean_jwks = _validate_jwks_public_only(jwks) if jwks is not None else None
    clean_jwks_uri = (
        _validate_url(jwks_uri, field_name="jwks_uri")
        if jwks_uri and jwks_uri.strip()
        else None
    )
    if auth_method == "private_key_jwt" and clean_jwks is None and clean_jwks_uri is None:
        raise OAuthClientConfigInvalid(
            "private_key_jwt requires jwks or jwks_uri"
        )

    clean_grants = tuple(dict.fromkeys(g.strip() for g in grant_types if g.strip()))
    if not clean_grants or any(g not in SUPPORTED_GRANT_TYPES for g in clean_grants):
        raise OAuthClientConfigInvalid("allowed_grant_types contains unsupported values")

    clean_audiences = tuple(
        dict.fromkeys(a.strip() for a in subject_audiences if a.strip())
    )
    if GRANT_TYPE_TOKEN_EXCHANGE in clean_grants and not clean_audiences:
        raise OAuthClientConfigInvalid(
            "allowed_subject_audiences is required when token-exchange is enabled"
        )

    clean_surfaces = tuple(dict.fromkeys(s.strip() for s in surfaces if s.strip()))
    if not clean_surfaces or any(s not in SUPPORTED_SURFACES for s in clean_surfaces):
        raise OAuthClientConfigInvalid("allowed_surfaces contains unsupported values")

    clean_scopes = tuple(dict.fromkeys(s.strip() for s in scopes if s.strip()))
    if not clean_scopes:
        raise OAuthClientConfigInvalid("allowed_scopes must not be empty")
    if any(s not in ALL_PERMISSIONS for s in clean_scopes):
        raise OAuthClientConfigInvalid("allowed_scopes contains unknown permissions")
    if FORBIDDEN_DELEGATED_SCOPES.intersection(clean_scopes):
        raise OAuthClientScopeForbidden()

    if token_ttl_sec is not None and not (60 <= token_ttl_sec <= 3600):
        raise OAuthClientConfigInvalid("token_ttl_sec must be between 60 and 3600")

    return (
        cleaned_name,
        clean_jwks,
        clean_jwks_uri,
        clean_grants,
        clean_audiences,
        clean_surfaces,
        clean_scopes,
    )


def create_oauth_client(
    *,
    name: str,
    description: str | None,
    provider_id: str,
    enabled: bool,
    token_endpoint_auth_method: str,
    jwks: dict[str, Any] | None,
    jwks_uri: str | None,
    allowed_grant_types: list[str],
    allowed_subject_audiences: list[str],
    allowed_surfaces: list[str],
    allowed_scopes: list[str],
    token_ttl_sec: int | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
    store: OAuthClientStore,
    providers: ProviderStore,
) -> tuple[OAuthClientRecord, str | None]:
    if providers.get(provider_id) is None:
        raise ProviderNotFound()

    (
        cleaned_name,
        clean_jwks,
        clean_jwks_uri,
        clean_grants,
        clean_audiences,
        clean_surfaces,
        clean_scopes,
    ) = _validate_client_fields(
        name=name,
        auth_method=token_endpoint_auth_method,
        jwks=jwks,
        jwks_uri=jwks_uri,
        grant_types=allowed_grant_types,
        subject_audiences=allowed_subject_audiences,
        surfaces=allowed_surfaces,
        scopes=allowed_scopes,
        token_ttl_sec=token_ttl_sec,
    )

    plaintext_secret: str | None = None
    secret_prefix: str | None = None
    secret_hash: str | None = None
    if token_endpoint_auth_method != "private_key_jwt":
        plaintext_secret, secret_prefix, secret_hash = _generate_client_secret()

    now = utc_now()
    record = OAuthClientRecord(
        id=f"ocl_{secrets.token_hex(6)}",
        client_id=f"rfq_cid_{secrets.token_hex(8)}",
        name=cleaned_name,
        description=description.strip() if description else None,
        provider_id=provider_id,
        enabled=enabled,
        token_endpoint_auth_method=token_endpoint_auth_method,
        jwks=clean_jwks,
        jwks_uri=clean_jwks_uri,
        secret_hash=secret_hash,
        secret_prefix=secret_prefix,
        allowed_grant_types=clean_grants,
        allowed_subject_audiences=clean_audiences,
        allowed_surfaces=clean_surfaces,
        allowed_scopes=clean_scopes,
        token_ttl_sec=token_ttl_sec,
        created_at=now,
        updated_at=now,
    )
    saved = store.save(record)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="oauth_client",
        resource_id=saved.id,
        action="create",
        result="success",
        detail={"client_id": saved.client_id, "provider_id": saved.provider_id},
    )
    return saved, plaintext_secret


def update_oauth_client(
    *,
    record_id: str,
    patch: dict[str, Any],
    actor_user_id: str | None,
    actor_token_id: str | None,
    store: OAuthClientStore,
    runtime: OAuthRuntimeStore,
) -> OAuthClientRecord:
    existing = store.get_by_id(record_id)
    if existing is None:
        raise OAuthClientNotFound()

    name = patch.get("name", existing.name)
    description = (
        patch["description"].strip()
        if "description" in patch and patch["description"] is not None
        else (None if "description" in patch else existing.description)
    )
    enabled = bool(patch.get("enabled", existing.enabled))
    auth_method = patch.get(
        "token_endpoint_auth_method", existing.token_endpoint_auth_method
    )
    jwks = patch["jwks"] if "jwks" in patch else existing.jwks
    jwks_uri = patch["jwks_uri"] if "jwks_uri" in patch else existing.jwks_uri
    grant_types = list(patch.get("allowed_grant_types", existing.allowed_grant_types))
    subject_audiences = list(
        patch.get("allowed_subject_audiences", existing.allowed_subject_audiences)
    )
    surfaces = list(patch.get("allowed_surfaces", existing.allowed_surfaces))
    scopes = list(patch.get("allowed_scopes", existing.allowed_scopes))
    token_ttl_sec = (
        patch["token_ttl_sec"] if "token_ttl_sec" in patch else existing.token_ttl_sec
    )

    (
        cleaned_name,
        clean_jwks,
        clean_jwks_uri,
        clean_grants,
        clean_audiences,
        clean_surfaces,
        clean_scopes,
    ) = _validate_client_fields(
        name=name,
        auth_method=auth_method,
        jwks=jwks,
        jwks_uri=jwks_uri,
        grant_types=grant_types,
        subject_audiences=subject_audiences,
        surfaces=surfaces,
        scopes=scopes,
        token_ttl_sec=token_ttl_sec,
    )

    secret_hash = existing.secret_hash
    secret_prefix = existing.secret_prefix
    if auth_method == "private_key_jwt":
        secret_hash = None
        secret_prefix = None

    updated = replace(
        existing,
        name=cleaned_name,
        description=description,
        enabled=enabled,
        token_endpoint_auth_method=auth_method,
        jwks=clean_jwks,
        jwks_uri=clean_jwks_uri,
        secret_hash=secret_hash,
        secret_prefix=secret_prefix,
        allowed_grant_types=clean_grants,
        allowed_subject_audiences=clean_audiences,
        allowed_surfaces=clean_surfaces,
        allowed_scopes=clean_scopes,
        token_ttl_sec=token_ttl_sec,
        updated_at=utc_now(),
    )
    saved = store.save(updated)
    if existing.enabled and not saved.enabled:
        runtime.revoke_for_client(saved.client_id)

    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="oauth_client",
        resource_id=saved.id,
        action="update",
        result="success",
        detail={"enabled": saved.enabled},
    )
    return saved


def rotate_oauth_client_secret(
    *,
    record_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
    store: OAuthClientStore,
) -> tuple[OAuthClientRecord, str]:
    existing = store.get_by_id(record_id)
    if existing is None:
        raise OAuthClientNotFound()
    if existing.token_endpoint_auth_method == "private_key_jwt":
        raise OAuthClientSecretUnsupported()
    plaintext, prefix, secret_hash = _generate_client_secret()
    updated = replace(
        existing,
        secret_hash=secret_hash,
        secret_prefix=prefix,
        updated_at=utc_now(),
    )
    saved = store.save(updated)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="oauth_client",
        resource_id=saved.id,
        action="rotate_secret",
        result="success",
        detail={"secret_prefix": prefix},
    )
    return saved, plaintext


def delete_oauth_client(
    *,
    record_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
    store: OAuthClientStore,
    runtime: OAuthRuntimeStore,
) -> None:
    existing = store.get_by_id(record_id)
    if existing is None:
        raise OAuthClientNotFound()
    runtime.revoke_for_client(existing.client_id)
    store.delete(record_id)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="oauth_client",
        resource_id=existing.id,
        action="delete",
        result="success",
        detail={"client_id": existing.client_id},
    )


@dataclass(frozen=True)
class TokenGrantRequest:
    grant_type: str
    authorization_header: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    client_assertion_type: str | None = None
    client_assertion: str | None = None
    assertion: str | None = None
    subject_token: str | None = None
    resource: str | None = None
    scope: str | None = None


@dataclass(frozen=True)
class TokenExchangeResult:
    access_token: str
    token_type: str
    issued_token_type: str
    expires_in: int
    scope: str


def _parse_basic_auth(header: str | None) -> tuple[str, str] | None:
    if not header or not header.lower().startswith("basic "):
        return None
    raw = header[6:].strip()
    try:
        decoded = base64.b64decode(raw).decode("utf-8")
    except Exception as exc:
        raise OAuthTokenError(
            "invalid_client", "Client authentication failed", http_status=401
        ) from exc
    if ":" not in decoded:
        raise OAuthTokenError(
            "invalid_client", "Client authentication failed", http_status=401
        )
    cid, secret = decoded.split(":", 1)
    return cid, secret


def _authenticate_client(
    *,
    origin: VerifiedOrigin,
    req: TokenGrantRequest,
    clients: OAuthClientStore,
    runtime: OAuthRuntimeStore,
    http: OidcHttpPort,
) -> OAuthClientRecord:
    basic = _parse_basic_auth(req.authorization_header)
    if req.client_assertion_type or req.client_assertion:
        if req.client_assertion_type != CLIENT_ASSERTION_TYPE_JWT or not req.client_assertion:
            raise OAuthTokenError(
                "invalid_client", "Invalid client_assertion_type", http_status=401
            )
        return _authenticate_private_key_jwt(
            origin=origin,
            assertion_jwt=req.client_assertion,
            declared_client_id=req.client_id,
            clients=clients,
            runtime=runtime,
            http=http,
        )

    if basic is not None:
        cid, secret = basic
        client = clients.get_by_client_id(cid)
        if (
            client is None
            or not client.enabled
            or client.token_endpoint_auth_method != "client_secret_basic"
            or not client.secret_hash
            or not hmac.compare_digest(client.secret_hash, _hash_secret(secret))
        ):
            raise OAuthTokenError(
                "invalid_client", "Client authentication failed", http_status=401
            )
        return client

    if req.client_id and req.client_secret:
        client = clients.get_by_client_id(req.client_id)
        if (
            client is None
            or not client.enabled
            or client.token_endpoint_auth_method != "client_secret_post"
            or not client.secret_hash
            or not hmac.compare_digest(client.secret_hash, _hash_secret(req.client_secret))
        ):
            raise OAuthTokenError(
                "invalid_client", "Client authentication failed", http_status=401
            )
        return client

    raise OAuthTokenError(
        "invalid_client", "Client credentials are required", http_status=401
    )


def _authenticate_private_key_jwt(
    *,
    origin: VerifiedOrigin,
    assertion_jwt: str,
    declared_client_id: str | None,
    clients: OAuthClientStore,
    runtime: OAuthRuntimeStore,
    http: OidcHttpPort,
) -> OAuthClientRecord:
    try:
        header = jwt.get_unverified_header(assertion_jwt)
        unverified = jwt.decode(assertion_jwt, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise OAuthTokenError(
            "invalid_client", "Malformed client_assertion", http_status=401
        ) from exc

    alg = header.get("alg")
    if not isinstance(alg, str) or alg not in ALLOWED_ALGS:
        raise OAuthTokenError(
            "invalid_client", "Unsupported client_assertion algorithm", http_status=401
        )
    kid = header.get("kid")
    if kid is not None and not isinstance(kid, str):
        raise OAuthTokenError(
            "invalid_client", "Invalid client_assertion kid", http_status=401
        )
    sub = unverified.get("sub")
    iss = unverified.get("iss")
    if not isinstance(sub, str) or not sub or iss != sub:
        raise OAuthTokenError(
            "invalid_client", "client_assertion iss and sub must match client_id", http_status=401
        )
    if declared_client_id and declared_client_id != sub:
        raise OAuthTokenError(
            "invalid_client", "client_id does not match client_assertion sub", http_status=401
        )

    client = clients.get_by_client_id(sub)
    if (
        client is None
        or not client.enabled
        or client.token_endpoint_auth_method != "private_key_jwt"
    ):
        raise OAuthTokenError(
            "invalid_client", "Client authentication failed", http_status=401
        )

    key = None
    if client.jwks is not None:
        key = find_key_in_jwks(client.jwks, kid)
    if key is None and client.jwks_uri:
        try:
            key = signing_key(client.jwks_uri, kid, alg, http=http)
        except SsoProviderUnavailable as exc:
            raise OAuthTokenError(
                "temporarily_unavailable", "Unable to fetch client JWKS", http_status=503
            ) from exc
        except SsoAssertionRejected as exc:
            raise OAuthTokenError(
                "invalid_client", "Client signing key not found", http_status=401
            ) from exc
    if key is None:
        raise OAuthTokenError(
            "invalid_client", "Client signing key not found", http_status=401
        )

    allowed_auds = [origin.oauth_issuer(), origin.oauth_token_endpoint()]
    try:
        claims = jwt.decode(
            assertion_jwt,
            key=key,
            algorithms=[alg],
            issuer=client.client_id,
            audience=allowed_auds,
            options={"require": ["iss", "sub", "aud", "exp", "jti"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise OAuthTokenError(
            "invalid_client", "Invalid client_assertion signature or claims", http_status=401
        ) from exc

    now_ts = time.time()
    exp = float(claims["exp"])
    if exp - now_ts > _MAX_CLIENT_ASSERTION_TTL_SEC + 30:
        raise OAuthTokenError(
            "invalid_client", "client_assertion lifetime exceeds maximum", http_status=401
        )
    jti = claims.get("jti")
    if not isinstance(jti, str) or not jti:
        raise OAuthTokenError(
            "invalid_client", "client_assertion jti is required", http_status=401
        )
    ttl = min(max(int(exp - now_ts) + 30, 30), _MAX_JTI_TTL_SEC)
    if not runtime.consume_jti_once("client_assertion", client.client_id, jti, ttl):
        raise OAuthTokenError(
            "invalid_client", "client_assertion jti has already been used", http_status=401
        )
    return client


def _verify_idp_jwt(
    *,
    token: str,
    jwks_uri: str,
    issuer: str,
    allowed_algs: tuple[str, ...],
    expected_typ: str | None,
    allowed_audiences: list[str],
    require_jti: bool,
    http: OidcHttpPort,
) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise OAuthTokenError("invalid_grant", "Malformed JWT assertion") from exc
    if expected_typ is not None and header.get("typ") != expected_typ:
        raise OAuthTokenError(
            "invalid_grant", f"Expected JWT header typ={expected_typ}"
        )
    alg = header.get("alg")
    if not isinstance(alg, str) or alg not in ALLOWED_ALGS or alg not in allowed_algs:
        raise OAuthTokenError("invalid_grant", "Assertion signing algorithm not allowed")
    kid = header.get("kid")
    if kid is not None and not isinstance(kid, str):
        raise OAuthTokenError("invalid_grant", "Invalid assertion kid")
    try:
        key = signing_key(jwks_uri, kid, alg, http=http)
    except SsoProviderUnavailable as exc:
        raise OAuthTokenError(
            "temporarily_unavailable",
            "Identity provider JWKS is unavailable",
            http_status=503,
        ) from exc
    except SsoAssertionRejected as exc:
        raise OAuthTokenError("invalid_grant", "Assertion signing key unknown") from exc

    required = ["iss", "sub", "aud", "exp", "iat"]
    if require_jti:
        required.append("jti")
    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=[alg],
            issuer=issuer,
            audience=allowed_audiences,
            options={"require": required},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise OAuthTokenError(
            "invalid_grant", "Assertion verification failed"
        ) from exc
    return claims


def _resolve_target_surfaces(
    *,
    origin: VerifiedOrigin,
    resource_param: str | None,
    client: OAuthClientRecord,
) -> tuple[ResourceSurface, ...]:
    if resource_param:
        surface = origin.match_resource_uri(resource_param)
        if surface is None or surface.value not in client.allowed_surfaces:
            raise OAuthTokenError(
                "invalid_target",
                "Requested resource URI is not permitted for this client",
            )
        return (surface,)
    if len(client.allowed_surfaces) == 1:
        return (ResourceSurface(client.allowed_surfaces[0]),)
    raise OAuthTokenError(
        "invalid_target",
        "resource parameter is required when client allows multiple surfaces",
    )


def exchange_delegated_token(
    *,
    origin: VerifiedOrigin,
    req: TokenGrantRequest,
    http: OidcHttpPort,
    clients: OAuthClientStore,
    providers: ProviderStore,
    users: UserStore,
    roles: RoleStore,
    bindings: BindingStore,
    subjects: SubjectStore,
    runtime: OAuthRuntimeStore,
) -> TokenExchangeResult:
    """Authenticate client, verify ID-JAG or RFC 8693 assertion, admit user, mint rfq_oat_."""
    if req.grant_type not in SUPPORTED_GRANT_TYPES:
        raise OAuthTokenError("unsupported_grant_type", "Grant type is not supported")

    client = _authenticate_client(
        origin=origin,
        req=req,
        clients=clients,
        runtime=runtime,
        http=http,
    )
    if req.grant_type not in client.allowed_grant_types:
        raise OAuthTokenError(
            "unauthorized_client",
            "Client is not authorized for this grant type",
        )

    provider = providers.get(client.provider_id)
    if provider is None or not provider.enabled:
        raise OAuthTokenError(
            "invalid_grant", "Identity provider is disabled or missing"
        )

    try:
        metadata = discover(provider, http=http)
    except SsoProviderUnavailable as exc:
        raise OAuthTokenError(
            "temporarily_unavailable",
            "Identity provider discovery is unavailable",
            http_status=503,
        ) from exc
    except SsoAssertionRejected as exc:
        raise OAuthTokenError(
            "invalid_grant", "Identity provider metadata is invalid"
        ) from exc

    surfaces = _resolve_target_surfaces(
        origin=origin, resource_param=req.resource, client=client
    )

    if req.grant_type == GRANT_TYPE_ID_JAG:
        if not req.assertion:
            raise OAuthTokenError("invalid_request", "assertion parameter is required")
        claims = _verify_idp_jwt(
            token=req.assertion,
            jwks_uri=metadata.jwks_uri,
            issuer=provider.issuer,
            allowed_algs=metadata.id_token_signing_alg_values_supported,
            expected_typ=ID_JAG_HEADER_TYP,
            allowed_audiences=[origin.oauth_issuer()],
            require_jti=True,
            http=http,
        )
        raw_aud = claims.get("aud")
        if isinstance(raw_aud, list) and len(raw_aud) != 1:
            raise OAuthTokenError("invalid_grant", "ID-JAG aud must be a single value")
        claim_client_id = claims.get("client_id")
        if claim_client_id is not None and claim_client_id != client.client_id:
            raise OAuthTokenError(
                "invalid_grant", "ID-JAG client_id does not match authenticated client"
            )
        claim_resource = claims.get("resource")
        if isinstance(claim_resource, str) and claim_resource:
            matched = origin.match_resource_uri(claim_resource)
            if matched is None or matched not in surfaces:
                raise OAuthTokenError(
                    "invalid_target", "ID-JAG resource does not match requested target"
                )
        jti = str(claims["jti"])
        ttl = min(max(int(float(claims["exp"]) - time.time()) + 30, 30), _MAX_JTI_TTL_SEC)
        if not runtime.consume_jti_once("id_jag", provider.issuer, jti, ttl):
            raise OAuthTokenError("invalid_grant", "ID-JAG assertion has already been used")
    else:
        if not req.subject_token:
            raise OAuthTokenError("invalid_request", "subject_token parameter is required")
        claims = _verify_idp_jwt(
            token=req.subject_token,
            jwks_uri=metadata.jwks_uri,
            issuer=provider.issuer,
            allowed_algs=metadata.id_token_signing_alg_values_supported,
            expected_typ=None,
            allowed_audiences=list(client.allowed_subject_audiences),
            require_jti=False,
            http=http,
        )
        azp = claims.get("azp")
        if isinstance(azp, str) and azp not in client.allowed_subject_audiences:
            raise OAuthTokenError("invalid_grant", "subject_token azp is not permitted")

    try:
        external = assertion_from_claims(provider, claims)
        user = admit_external_subject(
            provider=provider,
            assertion=external,
            users=users,
            roles=roles,
            bindings=bindings,
            subjects=subjects,
            pending=None,
            mode="headless_oauth",
        )
    except (AuthAccountDisabled, SsoNotAdmitted, SsoAssertionRejected) as exc:
        raise OAuthTokenError("invalid_grant", exc.message) from exc

    role = roles.get_by_id(user.role_id) if user.role_id else None
    user_perms = frozenset(effective_permissions(role)) if role is not None else frozenset()
    surface_ceiling: set[str] = set()
    for surface in surfaces:
        surface_ceiling.update(surface.ceiling)

    permitted = (
        user_perms
        & frozenset(client.allowed_scopes)
        & frozenset(surface_ceiling)
    ) - FORBIDDEN_DELEGATED_SCOPES

    if req.scope:
        requested = {item for item in req.scope.split() if item}
        if not requested or not requested.issubset(client.allowed_scopes):
            raise OAuthTokenError("invalid_scope", "Requested scope is not permitted")
        granted = permitted & requested
    else:
        granted = permitted

    if not granted:
        raise OAuthTokenError(
            "invalid_scope", "User holds none of the permitted delegated scopes"
        )

    ttl_sec = client.token_ttl_sec or oauth_access_token_ttl_sec()
    sorted_scopes = tuple(sorted(granted))
    surface_names = tuple(surface.value for surface in surfaces)
    token_record, plaintext = runtime.issue_token(
        user_id=user.id,
        client_id=client.client_id,
        provider_id=provider.id,
        scopes=sorted_scopes,
        surfaces=surface_names,
        ttl_sec=ttl_sec,
    )
    clients.touch_last_used(client.id)

    persist_audit_event(
        actor_user_id=user.id,
        actor_token_id=token_record.token_id,
        resource_type="oauth_token",
        resource_id=token_record.token_id,
        action="token_exchange",
        result="success",
        detail={
            "client_id": client.client_id,
            "provider_id": provider.id,
            "grant_type": req.grant_type,
            "surfaces": list(surface_names),
            "scopes": list(sorted_scopes),
        },
    )

    return TokenExchangeResult(
        access_token=plaintext,
        token_type="Bearer",
        issued_token_type=ISSUED_TOKEN_TYPE_ACCESS,
        expires_in=ttl_sec,
        scope=" ".join(sorted_scopes),
    )


def authorization_server_metadata(origin: VerifiedOrigin) -> dict[str, Any]:
    return {
        "issuer": origin.oauth_issuer(),
        "token_endpoint": origin.oauth_token_endpoint(),
        "grant_types_supported": [GRANT_TYPE_ID_JAG, GRANT_TYPE_TOKEN_EXCHANGE],
        "token_endpoint_auth_methods_supported": [
            "private_key_jwt",
            "client_secret_basic",
            "client_secret_post",
        ],
        "token_endpoint_auth_signing_alg_values_supported": list(ALLOWED_ALGS),
        "authorization_grant_profiles_supported": [
            "urn:ietf:params:oauth:grant-profile:id-jag"
        ],
    }


def protected_resource_metadata(
    origin: VerifiedOrigin, surface: ResourceSurface
) -> dict[str, Any]:
    return {
        "resource": origin.resource_uri(surface),
        "authorization_servers": [origin.oauth_issuer()],
        "bearer_methods_supported": ["header"],
        "scopes_supported": list(surface.advertised_scopes),
    }
