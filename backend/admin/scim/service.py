"""SCIM 2.0 Service Provider: provider-isolated Users/Groups reconciliation and Subject Attributes."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, replace
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.admin.errors import UserLastLocalSuperAdmin, UserNotFound, UserSystemImmutable
from backend.admin.federation.binding_store import BindingStore
from backend.admin.federation.provider_store import ProviderStore
from backend.admin.federation.spec import BindingRecord, ScimSubjectSource
from backend.admin.lifecycle import disable_user, enable_user
from backend.admin.oauth.runtime_store import OAuthRuntimeStore
from backend.admin.role_store import RoleStore
from backend.admin.scim.errors import ScimError
from backend.admin.scim.store import (
    SCIM_TOKEN_PREFIX,
    ScimGroupBindingRecord,
    ScimStore,
    hash_scim_token,
)
from backend.admin.session_store import SessionStore
from backend.admin.subjects.records import UserGroupRecord
from backend.admin.subjects.store import SubjectStore
from backend.admin.user_store import UserRecord, UserStore
from backend.core.time import format_instant, utc_now

SCHEMA_LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCHEMA_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCHEMA_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCHEMA_USER_EXT = "urn:ietf:params:scim:schemas:extension:refraq:2.0:User"
SCHEMA_GROUP_EXT = "urn:ietf:params:scim:schemas:extension:refraq:2.0:Group"
SCHEMA_SPC = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
SCHEMA_RESOURCE_TYPE = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"

_FILTER_EQ_RE = re.compile(
    r'^\s*([A-Za-z0-9_.:-]+)\s+eq\s+"([^"]*)"\s*$', re.IGNORECASE
)
_GROUP_KEY_CLEAN_RE = re.compile(r"[^a-z0-9_]+")
_ACCOUNT_CLEAN_RE = re.compile(r"[^a-zA-Z0-9_.-]")


@dataclass(frozen=True, slots=True)
class ScimProviderPrincipal:
    """Sealed SCIM caller bound to exactly one enabled Identity Provider."""

    provider_id: str
    issuer: str
    token_id: str
    scim_subject_source: ScimSubjectSource
    default_role_id: str | None


def authenticate_scim_bearer(
    authorization: str | None,
    *,
    scim_store: ScimStore,
    providers: ProviderStore,
) -> ScimProviderPrincipal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ScimError(401, "Missing SCIM Bearer token")
    secret = authorization[7:].strip()
    if not secret or not secret.startswith(SCIM_TOKEN_PREFIX):
        raise ScimError(401, "Invalid SCIM Bearer token")

    token = scim_store.get_token_by_hash(hash_scim_token(secret))
    if token is None or token.revoked_at is not None:
        raise ScimError(401, "Invalid or revoked SCIM Bearer token")

    provider = providers.get(token.provider_id)
    if provider is None or not provider.enabled:
        raise ScimError(401, "Identity provider is disabled or missing")

    scim_store.touch_token_last_used(token.id)
    return ScimProviderPrincipal(
        provider_id=provider.id,
        issuer=provider.issuer,
        token_id=token.id,
        scim_subject_source=provider.config.scim_subject_source,
        default_role_id=provider.config.default_role_id,
    )


def service_provider_config() -> dict[str, Any]:
    return {
        "schemas": [SCHEMA_SPC],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Per-Identity-Provider SCIM Bearer token (rfq_scim_...)",
                "primary": True,
            }
        ],
    }


def resource_types() -> dict[str, Any]:
    items = [
        {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "schema": SCHEMA_USER,
            "schemaExtensions": [{"schema": SCHEMA_USER_EXT, "required": False}],
        },
        {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "schema": SCHEMA_GROUP,
            "schemaExtensions": [{"schema": SCHEMA_GROUP_EXT, "required": False}],
        },
    ]
    return {
        "schemas": [SCHEMA_LIST],
        "totalResults": len(items),
        "startIndex": 1,
        "itemsPerPage": len(items),
        "Resources": items,
    }


def schemas_list() -> dict[str, Any]:
    items = [
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": SCHEMA_USER,
            "name": "User",
            "description": "SCIM 2.0 User",
        },
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": SCHEMA_GROUP,
            "name": "Group",
            "description": "SCIM 2.0 Group",
        },
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": SCHEMA_USER_EXT,
            "name": "RefraqUserAttributes",
            "description": "refraq Subject Attribute extension for Users",
        },
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": SCHEMA_GROUP_EXT,
            "name": "RefraqGroupAttributes",
            "description": "refraq Subject Attribute extension for Groups",
        },
    ]
    return {
        "schemas": [SCHEMA_LIST],
        "totalResults": len(items),
        "startIndex": 1,
        "itemsPerPage": len(items),
        "Resources": items,
    }


def _parse_eq_filter(expr: str | None) -> tuple[str, str] | None:
    if not expr or not expr.strip():
        return None
    match = _FILTER_EQ_RE.match(expr)
    if match is None:
        raise ScimError(
            400,
            "Only simple equality filters (e.g. userName eq \"value\") are supported",
            scim_type="invalidFilter",
        )
    return match.group(1).lower(), match.group(2)


def _extract_email(payload: dict[str, Any]) -> str | None:
    emails = payload.get("emails")
    if isinstance(emails, list):
        primary = next(
            (
                item.get("value")
                for item in emails
                if isinstance(item, dict) and item.get("primary") and isinstance(item.get("value"), str)
            ),
            None,
        )
        if primary:
            return primary.strip()
        for item in emails:
            if isinstance(item, dict) and isinstance(item.get("value"), str) and item["value"].strip():
                return item["value"].strip()
    return None


def _extract_display_name(payload: dict[str, Any], fallback: str) -> str:
    raw = payload.get("displayName")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:128]
    name = payload.get("name")
    if isinstance(name, dict):
        formatted = name.get("formatted")
        if isinstance(formatted, str) and formatted.strip():
            return formatted.strip()[:128]
        parts = [
            str(name.get("givenName") or "").strip(),
            str(name.get("familyName") or "").strip(),
        ]
        joined = " ".join(part for part in parts if part)
        if joined:
            return joined[:128]
    return fallback[:128]


def _derive_subject(principal: ScimProviderPrincipal, payload: dict[str, Any]) -> str:
    user_name = str(payload.get("userName") or "").strip()
    external_id = str(payload.get("externalId") or "").strip()
    if principal.scim_subject_source == "user_name":
        subject = user_name or external_id
    else:
        subject = external_id or user_name
    if not subject:
        raise ScimError(400, "userName or externalId is required", scim_type="invalidValue")
    return subject[:255]


def _clean_account(raw: str) -> str:
    return _ACCOUNT_CLEAN_RE.sub("_", raw.strip())[:64]


def _sync_subject_attributes(
    *,
    subject_type: str,
    subject_id: str,
    ext_payload: Any,
    subjects: SubjectStore,
) -> None:
    if not isinstance(ext_payload, dict):
        raise ScimError(
            400, "Extension payload must be an object", scim_type="invalidValue"
        )
    defs_list, _total = subjects.list_definitions(limit=None, offset=0)
    by_key = {defn.key: defn for defn in defs_list}
    existing_map = subjects.values_for(subject_type, [subject_id]).get(subject_id, {})  # type: ignore[arg-type]
    merged: dict[str, tuple[str, ...]] = dict(existing_map)

    for key, raw_val in ext_payload.items():
        defn = by_key.get(key)
        if defn is None:
            raise ScimError(
                400,
                f"Unknown refraq subject attribute '{key}'",
                scim_type="invalidValue",
            )
        if raw_val is None or raw_val == "" or raw_val == []:
            merged.pop(defn.id, None)
            continue
        if isinstance(raw_val, list):
            values = tuple(str(item).strip() for item in raw_val if str(item).strip())
        else:
            values = (str(raw_val).strip(),)
        if not defn.multi_value and len(values) > 1:
            raise ScimError(
                400,
                f"Subject attribute '{key}' does not allow multiple values",
                scim_type="invalidValue",
            )
        merged[defn.id] = values

    subjects.replace_values(subject_type, subject_id, merged)  # type: ignore[arg-type]


def _present_user(
    user: UserRecord,
    binding: BindingRecord,
    subjects: SubjectStore,
) -> dict[str, Any]:
    defs_list, _total = subjects.list_definitions(limit=None, offset=0)
    id_to_def = {defn.id: defn for defn in defs_list}
    stored = subjects.values_for("user", [user.id]).get(user.id, {})
    ext: dict[str, Any] = {}
    for def_id, vals in stored.items():
        defn = id_to_def.get(def_id)
        if defn is None:
            continue
        ext[defn.key] = list(vals) if defn.multi_value else (vals[0] if vals else None)

    schemas = [SCHEMA_USER]
    payload: dict[str, Any] = {
        "schemas": schemas,
        "id": user.id,
        "externalId": binding.subject,
        "userName": user.account,
        "displayName": user.display_name,
        "active": user.status == "active",
        "emails": [{"value": user.email, "primary": True}] if user.email else [],
        "meta": {
            "resourceType": "User",
            "created": format_instant(user.created_at),
        },
    }
    if ext:
        schemas.append(SCHEMA_USER_EXT)
        payload[SCHEMA_USER_EXT] = ext
    return payload


def _list_provider_users(
    principal: ScimProviderPrincipal,
    *,
    bindings: BindingStore,
    users: UserStore,
) -> list[tuple[UserRecord, BindingRecord]]:
    result: list[tuple[UserRecord, BindingRecord]] = []
    for binding in bindings.list_for_issuer(principal.issuer):
        if binding.scim_deprovisioned_at is not None:
            continue
        user = users.get_by_id(binding.user_id)
        if user is None:
            continue
        result.append((user, binding))
    return result


def list_scim_users(
    principal: ScimProviderPrincipal,
    *,
    filter_expr: str | None = None,
    start_index: int = 1,
    count: int = 100,
    bindings: BindingStore,
    users: UserStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    pairs = _list_provider_users(principal, bindings=bindings, users=users)
    parsed_filter = _parse_eq_filter(filter_expr)
    if parsed_filter is not None:
        attr, val = parsed_filter
        if attr == "username":
            pairs = [pair for pair in pairs if pair[0].account.lower() == val.lower()]
        elif attr == "externalid":
            pairs = [pair for pair in pairs if pair[1].subject == val]
        else:
            raise ScimError(
                400, f"Unsupported filter attribute '{attr}'", scim_type="invalidFilter"
            )

    total = len(pairs)
    sliced = pairs[start_index - 1 : start_index - 1 + count]
    resources = [_present_user(u, b, subjects) for u, b in sliced]
    return {
        "schemas": [SCHEMA_LIST],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def _require_provider_user(
    principal: ScimProviderPrincipal,
    user_id: str,
    *,
    bindings: BindingStore,
    users: UserStore,
) -> tuple[UserRecord, BindingRecord]:
    binding = bindings.get_for_user(user_id)
    if (
        binding is None
        or binding.issuer != principal.issuer
        or binding.scim_deprovisioned_at is not None
    ):
        raise ScimError(404, "User not found")
    user = users.get_by_id(user_id)
    if user is None:
        raise ScimError(404, "User not found")
    return user, binding


def get_scim_user(
    principal: ScimProviderPrincipal,
    user_id: str,
    *,
    bindings: BindingStore,
    users: UserStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    user, binding = _require_provider_user(
        principal,
        user_id,
        bindings=bindings,
        users=users,
    )
    return _present_user(user, binding, subjects)


def create_scim_user(
    principal: ScimProviderPrincipal,
    payload: dict[str, Any],
    *,
    bindings: BindingStore,
    users: UserStore,
    roles: RoleStore,
    sessions: SessionStore,
    oauth_runtime: OAuthRuntimeStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    binding_store = bindings
    user_store = users
    role_store = roles
    session_store = sessions
    runtime_store = oauth_runtime
    subject_store = subjects

    subject = _derive_subject(principal, payload)
    user_name = str(payload.get("userName") or subject).strip()
    display_name = _extract_display_name(payload, user_name)
    email = _extract_email(payload)
    active = bool(payload.get("active", True))
    now = utc_now()

    existing_binding = binding_store.get(principal.issuer, subject)
    if existing_binding is not None:
        if existing_binding.scim_deprovisioned_at is None:
            raise ScimError(
                409, "User with this external identity already exists", scim_type="uniqueness"
            )
        # Reactivate previously SCIM-deprovisioned binding in place.
        user = user_store.get_by_id(existing_binding.user_id)
        assert user is not None
        user_store.update_profile(
            user.id, display_name=display_name, email=email, set_email=True
        )
        binding_store.save(
            replace(
                existing_binding,
                provider_id=principal.provider_id,
                email=email,
                display_name=display_name,
                scim_deprovisioned_at=None,
            )
        )
        if active:
            user = enable_user(
                user_id=user.id,
                users=user_store,
                bindings=binding_store,
                actor_token_id=principal.token_id,
                clear_scim_deprovisioned=True,
                audit_detail={"scim_reactivate": True, "provider_id": principal.provider_id},
            )
        else:
            user = disable_user(
                user_id=user.id,
                users=user_store,
                roles=role_store,
                sessions=session_store,
                oauth_runtime=runtime_store,
                bindings=binding_store,
                actor_token_id=principal.token_id,
                audit_detail={"scim_active": False, "provider_id": principal.provider_id},
            )
        if SCHEMA_USER_EXT in payload:
            _sync_subject_attributes(
                subject_type="user",
                subject_id=user.id,
                ext_payload=payload[SCHEMA_USER_EXT],
                subjects=subject_store,
            )
        refreshed_binding = binding_store.get(principal.issuer, subject) or existing_binding
        return _present_user(user, refreshed_binding, subject_store)

    account = _clean_account(user_name)
    if user_store.get_by_account(account) is not None:
        raise ScimError(
            409, f"Account '{account}' already exists", scim_type="uniqueness"
        )

    user = user_store.create_user(
        account=account,
        display_name=display_name,
        password_hash=None,
        role_id=principal.default_role_id,
        identity_source="oidc",
        email=email,
        status="active" if active else "disabled",
    )
    binding = binding_store.save(
        BindingRecord(
            id=f"binding_{uuid.uuid4().hex[:12]}",
            issuer=principal.issuer,
            subject=subject,
            user_id=user.id,
            provider_id=principal.provider_id,
            email=email,
            display_name=display_name,
            linked_at=now,
            last_login_at=None,
            scim_deprovisioned_at=None,
        )
    )
    if SCHEMA_USER_EXT in payload:
        _sync_subject_attributes(
            subject_type="user",
            subject_id=user.id,
            ext_payload=payload[SCHEMA_USER_EXT],
            subjects=subject_store,
        )
    persist_audit_event(
        actor_user_id=None,
        actor_token_id=principal.token_id,
        resource_type="user",
        resource_id=user.id,
        action="scim_create",
        result="success",
        detail={"provider_id": principal.provider_id, "subject": subject},
    )
    return _present_user(user, binding, subject_store)


def _apply_user_status(
    *,
    principal: ScimProviderPrincipal,
    user: UserRecord,
    active: bool,
    users: UserStore,
    roles: RoleStore,
    sessions: SessionStore,
    oauth_runtime: OAuthRuntimeStore,
    bindings: BindingStore,
) -> UserRecord:
    try:
        if not active and user.status == "active":
            return disable_user(
                user_id=user.id,
                users=users,
                roles=roles,
                sessions=sessions,
                oauth_runtime=oauth_runtime,
                bindings=bindings,
                actor_token_id=principal.token_id,
                mark_scim_deprovisioned=False,
                audit_detail={"scim_active": False, "provider_id": principal.provider_id},
            )
        if active and user.status != "active":
            return enable_user(
                user_id=user.id,
                users=users,
                bindings=bindings,
                actor_token_id=principal.token_id,
                clear_scim_deprovisioned=True,
                audit_detail={"scim_active": True, "provider_id": principal.provider_id},
            )
    except (UserSystemImmutable, UserLastLocalSuperAdmin) as exc:
        raise ScimError(403, exc.message) from exc
    except UserNotFound as exc:
        raise ScimError(404, exc.message) from exc
    return user


def replace_scim_user(
    principal: ScimProviderPrincipal,
    user_id: str,
    payload: dict[str, Any],
    *,
    bindings: BindingStore,
    users: UserStore,
    roles: RoleStore,
    sessions: SessionStore,
    oauth_runtime: OAuthRuntimeStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    binding_store = bindings
    user_store = users
    role_store = roles
    session_store = sessions
    runtime_store = oauth_runtime
    subject_store = subjects

    user, binding = _require_provider_user(
        principal, user_id, bindings=binding_store, users=user_store
    )
    display_name = _extract_display_name(payload, user.display_name)
    email = _extract_email(payload)
    updated = user_store.update_profile(
        user.id, display_name=display_name, email=email, set_email=True
    )
    assert updated is not None
    binding_store.save(
        replace(binding, email=email, display_name=display_name)
    )
    if "active" in payload:
        updated = _apply_user_status(
            principal=principal,
            user=updated,
            active=bool(payload["active"]),
            users=user_store,
            roles=role_store,
            sessions=session_store,
            oauth_runtime=runtime_store,
            bindings=binding_store,
        )
    if SCHEMA_USER_EXT in payload:
        _sync_subject_attributes(
            subject_type="user",
            subject_id=updated.id,
            ext_payload=payload[SCHEMA_USER_EXT],
            subjects=subject_store,
        )
    return _present_user(updated, binding, subject_store)


def patch_scim_user(
    principal: ScimProviderPrincipal,
    user_id: str,
    payload: dict[str, Any],
    *,
    bindings: BindingStore,
    users: UserStore,
    roles: RoleStore,
    sessions: SessionStore,
    oauth_runtime: OAuthRuntimeStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    binding_store = bindings
    user_store = users
    role_store = roles
    session_store = sessions
    runtime_store = oauth_runtime
    subject_store = subjects

    user, binding = _require_provider_user(
        principal, user_id, bindings=binding_store, users=user_store
    )
    ops = payload.get("Operations")
    if not isinstance(ops, list):
        raise ScimError(400, "Operations array is required", scim_type="invalidSyntax")

    display_name = user.display_name
    email = user.email
    active_change: bool | None = None
    ext_updates: dict[str, Any] = {}

    for op_item in ops:
        if not isinstance(op_item, dict):
            raise ScimError(
                400, "Each patch operation must be an object", scim_type="invalidSyntax"
            )
        op = str(op_item.get("op") or "").lower()
        path = str(op_item.get("path") or "").strip()
        value = op_item.get("value")

        if not path and isinstance(value, dict):
            if "active" in value:
                active_change = bool(value["active"])
            if "displayName" in value and isinstance(value["displayName"], str):
                display_name = value["displayName"].strip()[:128] or display_name
            if "emails" in value:
                email = _extract_email(value)
            if SCHEMA_USER_EXT in value:
                if not isinstance(value[SCHEMA_USER_EXT], dict):
                    raise ScimError(
                        400,
                        "Extension payload must be an object",
                        scim_type="invalidValue",
                    )
                ext_updates.update(value[SCHEMA_USER_EXT])
            continue

        lower_path = path.lower()
        if lower_path == "active":
            active_change = bool(value) if op != "remove" else False
        elif lower_path == "displayname":
            if op == "remove" or not isinstance(value, str) or not value.strip():
                raise ScimError(
                    400,
                    "displayName requires a non-empty string",
                    scim_type="invalidValue",
                )
            display_name = value.strip()[:128]
        elif lower_path.startswith("emails"):
            if op == "remove":
                email = None
            elif isinstance(value, str):
                email = value.strip() or None
            elif isinstance(value, list):
                email = _extract_email({"emails": value})
            else:
                raise ScimError(
                    400,
                    "emails value must be a string or array",
                    scim_type="invalidValue",
                )
        elif path.startswith(f"{SCHEMA_USER_EXT}:"):
            attr_key = path[len(SCHEMA_USER_EXT) + 1 :]
            ext_updates[attr_key] = None if op == "remove" else value
        elif path == SCHEMA_USER_EXT:
            if not isinstance(value, dict):
                raise ScimError(
                    400,
                    "Extension payload must be an object",
                    scim_type="invalidValue",
                )
            ext_updates.update(value)
        else:
            raise ScimError(
                400, f"Unsupported patch path '{path}'", scim_type="invalidPath"
            )

    updated = user_store.update_profile(
        user.id, display_name=display_name, email=email, set_email=True
    )
    assert updated is not None
    binding_store.save(replace(binding, email=email, display_name=display_name))
    if active_change is not None:
        updated = _apply_user_status(
            principal=principal,
            user=updated,
            active=active_change,
            users=user_store,
            roles=role_store,
            sessions=session_store,
            oauth_runtime=runtime_store,
            bindings=binding_store,
        )
    if ext_updates:
        _sync_subject_attributes(
            subject_type="user",
            subject_id=updated.id,
            ext_payload=ext_updates,
            subjects=subject_store,
        )
    return _present_user(updated, binding, subject_store)


def delete_scim_user(
    principal: ScimProviderPrincipal,
    user_id: str,
    *,
    bindings: BindingStore,
    users: UserStore,
    roles: RoleStore,
    sessions: SessionStore,
    oauth_runtime: OAuthRuntimeStore,
) -> None:
    binding_store = bindings
    user_store = users
    role_store = roles
    session_store = sessions
    runtime_store = oauth_runtime

    user, _binding = _require_provider_user(
        principal, user_id, bindings=binding_store, users=user_store
    )
    try:
        disable_user(
            user_id=user.id,
            users=user_store,
            roles=role_store,
            sessions=session_store,
            oauth_runtime=runtime_store,
            bindings=binding_store,
            actor_token_id=principal.token_id,
            mark_scim_deprovisioned=True,
            audit_detail={"scim_delete": True, "provider_id": principal.provider_id},
        )
    except (UserSystemImmutable, UserLastLocalSuperAdmin) as exc:
        raise ScimError(403, exc.message) from exc


# --- Groups reconciliation ---


def _group_key_from_name(name: str, fallback: str) -> str:
    slug = _GROUP_KEY_CLEAN_RE.sub("_", name.strip().lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"g_{slug or fallback}"
    return slug[:63]


def _present_group(
    group: UserGroupRecord,
    binding: ScimGroupBindingRecord,
    subjects: SubjectStore,
) -> dict[str, Any]:
    member_ids, _total = subjects.list_member_ids(group.id, limit=None, offset=0)
    defs_list, _dtotal = subjects.list_definitions(limit=None, offset=0)
    id_to_def = {defn.id: defn for defn in defs_list}
    stored = subjects.values_for("group", [group.id]).get(group.id, {})
    ext: dict[str, Any] = {}
    for def_id, vals in stored.items():
        defn = id_to_def.get(def_id)
        if defn is None:
            continue
        ext[defn.key] = list(vals) if defn.multi_value else (vals[0] if vals else None)

    schemas = [SCHEMA_GROUP]
    payload: dict[str, Any] = {
        "schemas": schemas,
        "id": group.id,
        "externalId": binding.external_id,
        "displayName": group.name,
        "members": [{"value": uid} for uid in member_ids],
        "meta": {
            "resourceType": "Group",
            "created": format_instant(group.created_at),
            "lastModified": format_instant(group.updated_at),
        },
    }
    if ext:
        schemas.append(SCHEMA_GROUP_EXT)
        payload[SCHEMA_GROUP_EXT] = ext
    return payload


def _extract_member_ids(raw_members: Any) -> list[str]:
    if not isinstance(raw_members, list):
        raise ScimError(400, "members must be an array", scim_type="invalidValue")
    out: list[str] = []
    for item in raw_members:
        if isinstance(item, dict) and isinstance(item.get("value"), str) and item["value"].strip():
            out.append(item["value"].strip())
    return list(dict.fromkeys(out))


def _sync_group_members(
    *,
    principal: ScimProviderPrincipal,
    group_id: str,
    desired_member_ids: list[str],
    bindings: BindingStore,
    subjects: SubjectStore,
) -> None:
    allowed_user_ids = {
        b.user_id
        for b in bindings.list_for_issuer(principal.issuer)
        if b.scim_deprovisioned_at is None
    }
    valid_desired = [uid for uid in desired_member_ids if uid in allowed_user_ids]
    current_ids, _total = subjects.list_member_ids(group_id, limit=None, offset=0)
    current_set = set(current_ids)
    desired_set = set(valid_desired)
    for uid in desired_set - current_set:
        subjects.add_member(group_id, uid)
    for uid in current_set - desired_set:
        subjects.remove_member(group_id, uid)


def list_scim_groups(
    principal: ScimProviderPrincipal,
    *,
    filter_expr: str | None = None,
    start_index: int = 1,
    count: int = 100,
    scim_store: ScimStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    store = scim_store
    subject_store = subjects
    pairs: list[tuple[UserGroupRecord, ScimGroupBindingRecord]] = []
    for binding in store.list_group_bindings(principal.provider_id):
        group = subject_store.get_group(binding.group_id)
        if group is not None:
            pairs.append((group, binding))

    parsed_filter = _parse_eq_filter(filter_expr)
    if parsed_filter is not None:
        attr, val = parsed_filter
        if attr == "displayname":
            pairs = [pair for pair in pairs if pair[0].name.lower() == val.lower()]
        elif attr == "externalid":
            pairs = [pair for pair in pairs if pair[1].external_id == val]
        else:
            raise ScimError(
                400, f"Unsupported filter attribute '{attr}'", scim_type="invalidFilter"
            )

    total = len(pairs)
    sliced = pairs[start_index - 1 : start_index - 1 + count]
    resources = [_present_group(g, b, subject_store) for g, b in sliced]
    return {
        "schemas": [SCHEMA_LIST],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def _require_provider_group(
    principal: ScimProviderPrincipal,
    group_id: str,
    *,
    scim_store: ScimStore,
    subjects: SubjectStore,
) -> tuple[UserGroupRecord, ScimGroupBindingRecord]:
    binding = scim_store.get_group_binding_by_group(principal.provider_id, group_id)
    if binding is None:
        raise ScimError(404, "Group not found")
    group = subjects.get_group(group_id)
    if group is None:
        raise ScimError(404, "Group not found")
    return group, binding


def get_scim_group(
    principal: ScimProviderPrincipal,
    group_id: str,
    *,
    scim_store: ScimStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    group, binding = _require_provider_group(
        principal,
        group_id,
        scim_store=scim_store,
        subjects=subjects,
    )
    return _present_group(group, binding, subjects)


def create_scim_group(
    principal: ScimProviderPrincipal,
    payload: dict[str, Any],
    *,
    scim_store: ScimStore,
    bindings: BindingStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    store = scim_store
    binding_store = bindings
    subject_store = subjects

    display_name = str(payload.get("displayName") or "").strip()
    if not display_name:
        raise ScimError(400, "displayName is required", scim_type="invalidValue")
    external_id = str(payload.get("externalId") or display_name).strip()[:255]
    if store.get_group_binding_by_external(principal.provider_id, external_id) is not None:
        raise ScimError(409, "Group already exists", scim_type="uniqueness")

    now = utc_now()
    group_id = f"grp_{uuid.uuid4().hex[:12]}"
    base_key = _group_key_from_name(display_name, group_id[-6:])
    all_groups, _total = subject_store.list_groups(limit=None, offset=0)
    existing_keys = {g.key for g in all_groups}
    key = base_key if base_key not in existing_keys else f"{base_key[:54]}_{group_id[-6:]}"

    group = subject_store.create_group(
        UserGroupRecord(
            id=group_id,
            key=key,
            name=display_name[:256],
            description=None,
            created_at=now,
            updated_at=now,
        )
    )
    group_binding = store.save_group_binding(
        ScimGroupBindingRecord(
            id=f"sgb_{uuid.uuid4().hex[:12]}",
            provider_id=principal.provider_id,
            external_id=external_id,
            group_id=group.id,
            created_at=now,
            updated_at=now,
        )
    )
    if "members" in payload:
        _sync_group_members(
            principal=principal,
            group_id=group.id,
            desired_member_ids=_extract_member_ids(payload.get("members")),
            bindings=binding_store,
            subjects=subject_store,
        )
    if SCHEMA_GROUP_EXT in payload:
        _sync_subject_attributes(
            subject_type="group",
            subject_id=group.id,
            ext_payload=payload[SCHEMA_GROUP_EXT],
            subjects=subject_store,
        )
    return _present_group(group, group_binding, subject_store)


def replace_scim_group(
    principal: ScimProviderPrincipal,
    group_id: str,
    payload: dict[str, Any],
    *,
    scim_store: ScimStore,
    bindings: BindingStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    store = scim_store
    binding_store = bindings
    subject_store = subjects
    group, binding = _require_provider_group(
        principal, group_id, scim_store=store, subjects=subject_store
    )
    display_name = str(payload.get("displayName") or group.name).strip()[:256]
    updated = subject_store.update_group(
        replace(group, name=display_name, updated_at=utc_now())
    )
    if "members" in payload:
        _sync_group_members(
            principal=principal,
            group_id=updated.id,
            desired_member_ids=_extract_member_ids(payload.get("members")),
            bindings=binding_store,
            subjects=subject_store,
        )
    if SCHEMA_GROUP_EXT in payload:
        _sync_subject_attributes(
            subject_type="group",
            subject_id=updated.id,
            ext_payload=payload[SCHEMA_GROUP_EXT],
            subjects=subject_store,
        )
    return _present_group(updated, binding, subject_store)


def patch_scim_group(
    principal: ScimProviderPrincipal,
    group_id: str,
    payload: dict[str, Any],
    *,
    scim_store: ScimStore,
    bindings: BindingStore,
    subjects: SubjectStore,
) -> dict[str, Any]:
    store = scim_store
    binding_store = bindings
    subject_store = subjects
    group, binding = _require_provider_group(
        principal, group_id, scim_store=store, subjects=subject_store
    )
    ops = payload.get("Operations")
    if not isinstance(ops, list):
        raise ScimError(400, "Operations array is required", scim_type="invalidSyntax")

    name = group.name
    current_ids, _total = subject_store.list_member_ids(group.id, limit=None, offset=0)
    member_set = set(current_ids)
    ext_updates: dict[str, Any] = {}

    for op_item in ops:
        if not isinstance(op_item, dict):
            raise ScimError(
                400, "Each patch operation must be an object", scim_type="invalidSyntax"
            )
        op = str(op_item.get("op") or "").lower()
        path = str(op_item.get("path") or "").strip()
        value = op_item.get("value")
        lower_path = path.lower()

        if lower_path == "displayname":
            if op == "remove" or not isinstance(value, str) or not value.strip():
                raise ScimError(
                    400,
                    "displayName requires a non-empty string",
                    scim_type="invalidValue",
                )
            name = value.strip()[:256]
        elif lower_path == "members":
            ids = _extract_member_ids(value)
            if op == "add":
                member_set.update(ids)
            elif op == "replace":
                member_set = set(ids)
            elif op == "remove":
                member_set.difference_update(ids)
            else:
                raise ScimError(
                    400,
                    f"Unsupported patch op '{op}' for members",
                    scim_type="invalidSyntax",
                )
        elif lower_path.startswith("members["):
            match = re.search(r'value\s+eq\s+"([^"]+)"', path, re.IGNORECASE)
            if not match or op != "remove":
                raise ScimError(
                    400,
                    f"Unsupported patch operation on '{path}'",
                    scim_type="invalidPath",
                )
            member_set.discard(match.group(1))
        elif path.startswith(f"{SCHEMA_GROUP_EXT}:"):
            attr_key = path[len(SCHEMA_GROUP_EXT) + 1 :]
            ext_updates[attr_key] = None if op == "remove" else value
        elif not path and isinstance(value, dict):
            if "displayName" in value and isinstance(value["displayName"], str):
                name = value["displayName"].strip()[:256] or name
            if "members" in value:
                ids = _extract_member_ids(value["members"])
                member_set = set(ids) if op == "replace" else (member_set | set(ids))
            if SCHEMA_GROUP_EXT in value:
                if not isinstance(value[SCHEMA_GROUP_EXT], dict):
                    raise ScimError(
                        400,
                        "Extension payload must be an object",
                        scim_type="invalidValue",
                    )
                ext_updates.update(value[SCHEMA_GROUP_EXT])
        else:
            raise ScimError(
                400, f"Unsupported patch path '{path}'", scim_type="invalidPath"
            )

    updated = subject_store.update_group(replace(group, name=name, updated_at=utc_now()))
    _sync_group_members(
        principal=principal,
        group_id=updated.id,
        desired_member_ids=sorted(member_set),
        bindings=binding_store,
        subjects=subject_store,
    )
    if ext_updates:
        _sync_subject_attributes(
            subject_type="group",
            subject_id=updated.id,
            ext_payload=ext_updates,
            subjects=subject_store,
        )
    return _present_group(updated, binding, subject_store)


def delete_scim_group(
    principal: ScimProviderPrincipal,
    group_id: str,
    *,
    scim_store: ScimStore,
    subjects: SubjectStore,
) -> None:
    store = scim_store
    subject_store = subjects
    group, _binding = _require_provider_group(
        principal, group_id, scim_store=store, subjects=subject_store
    )
    store.delete_group_binding(principal.provider_id, group.id)
    subject_store.delete_group(group.id)
