"""Identity Provider, SSO, claim, and unfederation orchestration."""

from __future__ import annotations

import uuid
from urllib.parse import unquote, urlsplit

from backend.admin.audit import persist_audit_event
from backend.admin.errors import UserAccountDuplicate, UserInvalidRole, UserNotFound
from backend.admin.federation.binding_store import BindingStore
from backend.admin.federation.config import (
    parse_oidc_config,
    validate_provider_config,
    validate_role_not_default_for_providers,
)
from backend.admin.federation.errors import (
    FederationAlreadyBound,
    FederationLastLocalSuperAdmin,
    FederationNotBound,
    FederationPasswordRequired,
    PendingIdentityExpired,
    PendingIdentityNotFound,
    ProviderIssuerDuplicate,
    ProviderIssuerImmutable,
    ProviderNotFound,
    ProviderProtocolUnsupported,
    SsoHandoffInvalid,
    SsoProviderUnavailable,
)
from backend.admin.federation.handoff_store import Handoff, new_handoff
from backend.admin.federation.pending_store import PendingStore
from backend.admin.federation.protocols.oidc.adapter import (
    authorization_url,
    exchange,
    pkce_challenge,
)
from backend.admin.federation.provider_store import ProviderStore
from backend.admin.federation.provisioning import admit
from backend.admin.federation.spec import BindingRecord, ProviderRecord, SUPPORTED_PROTOCOLS
from backend.admin.federation.transaction import federation_transaction
from backend.admin.role_store import RoleStore
from backend.admin.roles import SUPER_ADMIN_KEY
from backend.admin.security import hash_password
from backend.admin.session_store import SessionStore
from backend.admin.user_store import UserRecord, UserStore
from backend.core.time import utc_now

DEFAULT_FROM = "/console"


def _has_control_char(value: str) -> bool:
    return any(ord(char) < 32 or ord(char) == 127 for char in value)


def safe_from(value: str | None) -> str:
    """Same-origin relative return path. Mirrored by frontend `resolveFromPath`."""
    if not value:
        return DEFAULT_FROM
    if _has_control_char(value):
        return DEFAULT_FROM
    if not value.startswith("/") or len(value) == 1:
        return value if value == "/" else DEFAULT_FROM
    if value[1] in {"/", "\\"}:
        return DEFAULT_FROM
    parsed = urlsplit(value)
    decoded = unquote(value)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or "\\" in value
        or decoded.startswith("//")
        or "\\" in decoded
        or _has_control_char(decoded)
    ):
        return DEFAULT_FROM
    return value


def create_provider(
    *,
    store: ProviderStore,
    roles: RoleStore,
    protocol: str,
    display_name: str,
    enabled: bool,
    config_data: dict[str, object],
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> ProviderRecord:
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ProviderProtocolUnsupported()
    config = parse_oidc_config(config_data)
    validate_provider_config(config, roles)
    if store.get_by_issuer(config.issuer) is not None:
        raise ProviderIssuerDuplicate()
    now = utc_now()
    record = ProviderRecord(
        id=f"idp_{uuid.uuid4().hex[:12]}",
        protocol="oidc",
        display_name=display_name,
        issuer=config.issuer,
        enabled=enabled,
        config=config,
        created_at=now,
        updated_at=now,
    )
    saved = store.save(record)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="identity_provider",
        resource_id=saved.id,
        action="create",
        result="success",
    )
    return saved


def _cascade_disable_bound_users(
    *,
    bound: list[BindingRecord],
    users: UserStore,
    sessions: SessionStore,
    provider_id: str,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> int:
    disabled = 0
    for binding in bound:
        if actor_user_id is not None and binding.user_id == actor_user_id:
            continue
        updated = users.update_status(binding.user_id, "disabled")
        if updated is None:
            continue
        sessions.delete_by_user_id(binding.user_id)
        persist_audit_event(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            resource_type="user",
            resource_id=binding.user_id,
            action="disable",
            result="success",
            detail={"cascade_from_provider": provider_id},
        )
        disabled += 1
    return disabled


def patch_provider(
    *,
    store: ProviderStore,
    roles: RoleStore,
    provider_id: str,
    display_name: str | None,
    enabled: bool | None,
    config_data: dict[str, object] | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
    disable_bound_users: bool = False,
    bindings: BindingStore | None = None,
    users: UserStore | None = None,
    sessions: SessionStore | None = None,
) -> ProviderRecord:
    existing = store.get(provider_id)
    if existing is None:
        raise ProviderNotFound()
    merged = existing.config.to_dict()
    if config_data:
        for key, value in config_data.items():
            if value is not None:
                merged[key] = value
        if not config_data.get("client_secret"):
            merged["client_secret"] = existing.config.client_secret
    config = parse_oidc_config(merged)
    validate_provider_config(config, roles)
    if config.issuer != existing.issuer:
        raise ProviderIssuerImmutable()
    other = store.get_by_issuer(config.issuer)
    if other is not None and other.id != provider_id:
        raise ProviderIssuerDuplicate()
    now = utc_now()
    updated = ProviderRecord(
        id=existing.id,
        protocol="oidc",
        display_name=display_name if display_name is not None else existing.display_name,
        issuer=existing.issuer,
        enabled=enabled if enabled is not None else existing.enabled,
        config=config,
        created_at=existing.created_at,
        updated_at=now,
    )
    saved = store.save(updated)
    detail: dict[str, object] = {"enabled": saved.enabled}
    if enabled is False and bindings is not None:
        bound = bindings.list_for_issuer(saved.issuer)
        disabled = 0
        if disable_bound_users and users is not None and sessions is not None:
            disabled = _cascade_disable_bound_users(
                bound=bound,
                users=users,
                sessions=sessions,
                provider_id=provider_id,
                actor_user_id=actor_user_id,
                actor_token_id=actor_token_id,
            )
        detail.update(
            {
                "bound_user_count": len(bound),
                "disabled_user_count": disabled,
                "disable_bound_users": disable_bound_users,
            }
        )
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="identity_provider",
        resource_id=saved.id,
        action="update",
        result="success",
        detail=detail,
    )
    return saved


def delete_provider(
    *,
    store: ProviderStore,
    bindings: BindingStore,
    users: UserStore,
    sessions: SessionStore,
    provider_id: str,
    disable_bound_users: bool,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> int:
    existing = store.get(provider_id)
    if existing is None:
        raise ProviderNotFound()
    bound = bindings.list_for_issuer(existing.issuer)
    disabled = 0
    if disable_bound_users:
        disabled = _cascade_disable_bound_users(
            bound=bound,
            users=users,
            sessions=sessions,
            provider_id=provider_id,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
        )
    store.delete(provider_id)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="identity_provider",
        resource_id=provider_id,
        action="delete",
        result="success",
        detail={
            "bound_user_count": len(bound),
            "disabled_user_count": disabled,
            "disable_bound_users": disable_bound_users,
        },
    )
    return len(bound)


def start_sso(provider: ProviderRecord, redirect_uri: str, return_to: str) -> tuple[str, Handoff]:
    if not provider.enabled:
        raise SsoProviderUnavailable()
    handoff = new_handoff(provider.id, redirect_uri, safe_from(return_to))
    url = authorization_url(
        provider,
        redirect_uri=redirect_uri,
        state=handoff.state,
        nonce=handoff.nonce,
        code_challenge=pkce_challenge(handoff.verifier),
    )
    return url, handoff


def audit_sso_reject(
    *,
    provider_id: str,
    reason: str,
    cause: str | None = None,
) -> None:
    """Record an SSO rejection. Never include code, token, or claims."""
    detail: dict[str, object] = {"reason": reason, "provider_id": provider_id}
    if cause:
        detail["cause"] = cause
    persist_audit_event(
        actor_user_id=None,
        actor_token_id=None,
        resource_type="auth",
        resource_id=provider_id,
        action="sso_reject",
        result="denied",
        detail=detail,
    )


def complete_sso(
    *,
    provider: ProviderRecord,
    handoff: Handoff,
    code: str,
    response_iss: str | None,
    users: UserStore,
    roles: RoleStore,
    bindings: BindingStore,
    pending: PendingStore,
) -> UserRecord:
    if handoff.provider_id != provider.id:
        raise SsoHandoffInvalid()
    assertion = exchange(
        provider,
        code=code,
        redirect_uri=handoff.redirect_uri,
        code_verifier=handoff.verifier,
        nonce=handoff.nonce,
        response_iss=response_iss,
    )
    return admit(
        provider=provider,
        assertion=assertion,
        users=users,
        roles=roles,
        bindings=bindings,
        pending=pending,
    )


def _is_last_local_active_super_admin(
    user: UserRecord, users: UserStore, roles: RoleStore
) -> bool:
    if user.identity_source != "local" or user.status != "active" or not user.role_id:
        return False
    role = roles.get_by_id(user.role_id)
    if role is None or role.key != SUPER_ADMIN_KEY:
        return False
    return users.count_local_active_with_role(role.id) <= 1


def claim_pending(
    *,
    pending_id: str,
    user_id: str | None,
    create_account: str | None,
    create_display_name: str | None,
    create_email: str | None,
    create_role_id: str | None,
    pending: PendingStore,
    bindings: BindingStore,
    users: UserStore,
    roles: RoleStore,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> UserRecord:
    record = pending.get(pending_id)
    if record is None:
        raise PendingIdentityNotFound()
    if record.expires_at <= utc_now():
        raise PendingIdentityExpired()
    existing_user = users.get_by_id(user_id) if user_id else None
    if user_id:
        if existing_user is None:
            raise UserNotFound()
        if bindings.get_for_user(existing_user.id) is not None:
            raise FederationAlreadyBound()
        if _is_last_local_active_super_admin(existing_user, users, roles):
            raise FederationLastLocalSuperAdmin()
    else:
        if create_role_id is None or roles.get_by_id(create_role_id) is None:
            raise UserInvalidRole()
        account = (create_account or record.account_hint).strip()
        display_name = (create_display_name or record.display_name or account).strip()
        if users.get_by_account(account) is not None:
            raise UserAccountDuplicate()
    now = utc_now()
    with federation_transaction(
        users=users, bindings=bindings, pending=pending
    ) as session:
        if existing_user is not None:
            user = (
                users.update_identity_source(
                    existing_user.id, "oidc", session=session
                )
                or existing_user
            )
            users.update_password_hash(user.id, None, session=session)
        else:
            user = users.create_user(
                account=account,
                display_name=display_name,
                password_hash=None,
                role_id=create_role_id,
                identity_source="oidc",
                email=create_email if create_email is not None else record.email,
                session=session,
            )
        bindings.save(
            BindingRecord(
                id=f"binding_{uuid.uuid4().hex[:12]}",
                issuer=record.issuer,
                subject=record.subject,
                user_id=user.id,
                provider_id=record.provider_id,
                email=record.email,
                display_name=record.display_name,
                linked_at=now,
                last_login_at=None,
            ),
            session=session,
        )
        pending.delete(pending_id, session=session)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="pending_identity",
        resource_id=pending_id,
        action="claim",
        result="success",
        detail={"user_id": user.id},
    )
    return user


def unfederate_user(
    *,
    user_id: str,
    password: str | None,
    users: UserStore,
    bindings: BindingStore,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> UserRecord:
    user = users.get_by_id(user_id)
    if user is None:
        raise UserNotFound()
    binding = bindings.get_for_user(user_id)
    if binding is None and user.identity_source != "oidc":
        raise FederationNotBound()
    if not password:
        raise FederationPasswordRequired()
    password_hash = hash_password(password)
    with federation_transaction(users=users, bindings=bindings) as session:
        users.update_password_hash(user_id, password_hash, session=session)
        updated = (
            users.update_identity_source(user_id, "local", session=session) or user
        )
        bindings.delete_for_user(user_id, session=session)
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="user",
        resource_id=user_id,
        action="unfederate",
        result="success",
    )
    return updated
