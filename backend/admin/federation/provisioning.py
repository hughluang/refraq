"""Admission: binding, dual-mode auto-provision, scoped group_mappings sync, or pending queue."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from typing import Literal, NoReturn

from backend.admin.audit import persist_audit_event
from backend.admin.deps import resolve_user_permissions
from backend.admin.errors import AuthAccountDisabled, AuthConsoleAccessRequired
from backend.admin.federation.assertion import ExternalAssertion
from backend.admin.federation.binding_store import BindingStore
from backend.admin.federation.errors import SsoNotAdmitted
from backend.admin.federation.pending_store import PendingStore
from backend.admin.federation.protocols.oidc.claims import group_admission_reason
from backend.admin.federation.spec import (
    ACCOUNT_MAX_LEN,
    AdmissionReason,
    BindingRecord,
    PendingRecord,
    ProviderRecord,
)
from backend.admin.federation.transaction import federation_transaction
from backend.admin.parameters import sso_pending_ttl_days
from backend.admin.role_store import RoleStore
from backend.admin.roles import effective_permissions
from backend.admin.subjects.store import SubjectStore
from backend.admin.user_store import UserRecord, UserStore
from backend.core.time import utc_now

AdmissionMode = Literal["console_sso", "headless_oauth"]


def derive_account(assertion: ExternalAssertion) -> str:
    raw = assertion.preferred_username or assertion.email or assertion.subject
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]", "_", raw)[:ACCOUNT_MAX_LEN]
    return cleaned or "federated"


def _default_role_grants_console_access(
    provider: ProviderRecord, roles: RoleStore
) -> bool:
    role_id = provider.config.default_role_id
    role = roles.get_by_id(role_id) if role_id else None
    return role is not None and "console:access" in effective_permissions(role)


def _sync_mapped_groups(
    *,
    user_id: str,
    provider: ProviderRecord,
    assertion: ExternalAssertion,
    subjects: SubjectStore,
) -> None:
    """Scoped diff sync: (current - managed) | desired. Skipped on group overflow."""
    mappings = provider.config.group_mappings
    if not mappings or assertion.groups_overflow:
        return
    all_groups, _total = subjects.list_groups(limit=None, offset=0)
    by_key = {group.key: group.id for group in all_groups}

    managed_ids: set[str] = set()
    desired_ids: set[str] = set()
    asserted = set(assertion.groups)
    for mapping in mappings:
        gid = by_key.get(mapping.group_key)
        if gid is None:
            continue
        managed_ids.add(gid)
        if mapping.external_group in asserted:
            desired_ids.add(gid)

    if not managed_ids:
        return
    current_ids = set(subjects.group_ids_of(user_id))
    updated_ids = (current_ids - managed_ids) | desired_ids
    if updated_ids != current_ids:
        subjects.replace_user_groups(user_id, sorted(updated_ids))


def _reject_unadmitted(
    *,
    provider: ProviderRecord,
    assertion: ExternalAssertion,
    reason: AdmissionReason,
    mode: AdmissionMode,
    pending: PendingStore | None,
    actor_detail: dict[str, object],
) -> NoReturn:
    if mode == "console_sso" and pending is not None:
        now = utc_now()
        existing = pending.get_by_subject(assertion.issuer, assertion.subject)
        account_hint = derive_account(assertion)
        if existing is not None and existing.expires_at > now:
            existing.attempt_count += 1
            existing.last_attempt_at = now
            existing.admission_reason = reason
            existing.account_hint = account_hint
            existing.email = assertion.email
            existing.display_name = assertion.display_name
            existing.groups = assertion.groups
            existing.claims = dict(assertion.claims)
            existing.provider_id = provider.id
            pending.save(existing)
        else:
            ttl = timedelta(days=sso_pending_ttl_days())
            record = PendingRecord(
                id=existing.id
                if existing is not None
                else f"pending_{uuid.uuid4().hex[:12]}",
                issuer=assertion.issuer,
                subject=assertion.subject,
                account_hint=account_hint,
                admission_reason=reason,
                attempt_count=1,
                first_seen_at=now,
                last_attempt_at=now,
                expires_at=now + ttl,
                provider_id=provider.id,
                email=assertion.email,
                display_name=assertion.display_name,
                groups=assertion.groups,
                claims=dict(assertion.claims),
            )
            pending.save(record)
    persist_audit_event(
        actor_user_id=None,
        actor_token_id=None,
        resource_type="auth",
        resource_id=provider.id,
        action="sso_reject",
        result="denied",
        detail={**actor_detail, "mode": mode},
    )
    raise SsoNotAdmitted()


def admit_external_subject(
    *,
    provider: ProviderRecord,
    assertion: ExternalAssertion,
    users: UserStore,
    roles: RoleStore,
    bindings: BindingStore,
    subjects: SubjectStore,
    pending: PendingStore | None = None,
    mode: AdmissionMode = "console_sso",
) -> UserRecord:
    """Resolve or provision a User from a verified external assertion."""
    now = utc_now()
    binding = bindings.get(assertion.issuer, assertion.subject)
    if binding is not None:
        if binding.scim_deprovisioned_at is not None:
            persist_audit_event(
                actor_user_id=binding.user_id,
                actor_token_id=None,
                resource_type="auth",
                resource_id=provider.id,
                action="sso_reject",
                result="denied",
                detail={
                    "reason": "scim_deprovisioned",
                    "provider_id": provider.id,
                    "mode": mode,
                },
            )
            raise AuthAccountDisabled()
        user = users.get_by_id(binding.user_id)
        if user is None:
            persist_audit_event(
                actor_user_id=None,
                actor_token_id=None,
                resource_type="auth",
                resource_id=provider.id,
                action="sso_reject",
                result="denied",
                detail={
                    "reason": "bound_user_missing",
                    "provider_id": provider.id,
                    "mode": mode,
                },
            )
            raise SsoNotAdmitted()
        if user.status != "active":
            persist_audit_event(
                actor_user_id=user.id,
                actor_token_id=None,
                resource_type="auth",
                resource_id=provider.id,
                action="sso_reject",
                result="denied",
                detail={
                    "reason": "account_disabled",
                    "provider_id": provider.id,
                    "mode": mode,
                },
            )
            raise AuthAccountDisabled()
        if mode == "console_sso" and "console:access" not in resolve_user_permissions(
            user, roles
        ):
            persist_audit_event(
                actor_user_id=user.id,
                actor_token_id=None,
                resource_type="auth",
                resource_id=provider.id,
                action="sso_reject",
                result="denied",
                detail={
                    "reason": "console_access_required",
                    "provider_id": provider.id,
                },
            )
            raise AuthConsoleAccessRequired()
        if provider.config.auto_provision:
            reason = group_admission_reason(assertion, provider.config)
            if reason is not None:
                persist_audit_event(
                    actor_user_id=user.id,
                    actor_token_id=None,
                    resource_type="auth",
                    resource_id=provider.id,
                    action="sso_reject",
                    result="denied",
                    detail={
                        "reason": reason,
                        "provider_id": provider.id,
                        "bound": True,
                        "mode": mode,
                    },
                )
                raise SsoNotAdmitted()
        with federation_transaction(users=users, bindings=bindings) as session:
            users.update_last_login(user.id, now, session=session)
            binding.last_login_at = now
            binding.provider_id = provider.id
            bindings.save(binding, session=session)
        _sync_mapped_groups(
            user_id=user.id,
            provider=provider,
            assertion=assertion,
            subjects=subjects,
        )
        if mode == "console_sso":
            persist_audit_event(
                actor_user_id=user.id,
                actor_token_id=None,
                resource_type="auth",
                resource_id=provider.id,
                action="sso_login",
                result="success",
                detail={"provider_id": provider.id},
            )
        return user

    if provider.config.auto_provision:
        reason = group_admission_reason(assertion, provider.config)
        if reason is None:
            account = derive_account(assertion)
            if users.get_by_account(account) is None:
                if mode == "console_sso" and not _default_role_grants_console_access(
                    provider, roles
                ):
                    persist_audit_event(
                        actor_user_id=None,
                        actor_token_id=None,
                        resource_type="auth",
                        resource_id=provider.id,
                        action="sso_reject",
                        result="denied",
                        detail={
                            "reason": "console_access_required",
                            "provider_id": provider.id,
                            "default_role_id": provider.config.default_role_id,
                        },
                    )
                    raise AuthConsoleAccessRequired()
                with federation_transaction(users=users, bindings=bindings) as session:
                    user = users.create_user(
                        account=account,
                        display_name=assertion.display_name or account,
                        password_hash=None,
                        role_id=provider.config.default_role_id,
                        identity_source="oidc",
                        email=assertion.email,
                        session=session,
                    )
                    bindings.save(
                        BindingRecord(
                            id=f"binding_{uuid.uuid4().hex[:12]}",
                            issuer=assertion.issuer,
                            subject=assertion.subject,
                            user_id=user.id,
                            provider_id=provider.id,
                            email=assertion.email,
                            display_name=assertion.display_name,
                            linked_at=now,
                            last_login_at=now,
                        ),
                        session=session,
                    )
                    users.update_last_login(user.id, now, session=session)
                _sync_mapped_groups(
                    user_id=user.id,
                    provider=provider,
                    assertion=assertion,
                    subjects=subjects,
                )
                persist_audit_event(
                    actor_user_id=user.id,
                    actor_token_id=None,
                    resource_type="auth",
                    resource_id=provider.id,
                    action="sso_login" if mode == "console_sso" else "headless_provision",
                    result="success",
                    detail={"provider_id": provider.id, "provisioned": True, "mode": mode},
                )
                return user
            _reject_unadmitted(
                provider=provider,
                assertion=assertion,
                reason="account_collision",
                mode=mode,
                pending=pending,
                actor_detail={
                    "reason": "account_collision",
                    "provider_id": provider.id,
                },
            )
        _reject_unadmitted(
            provider=provider,
            assertion=assertion,
            reason=reason,
            mode=mode,
            pending=pending,
            actor_detail={"reason": reason, "provider_id": provider.id},
        )

    _reject_unadmitted(
        provider=provider,
        assertion=assertion,
        reason="auto_disabled",
        mode=mode,
        pending=pending,
        actor_detail={"reason": "auto_disabled", "provider_id": provider.id},
    )
