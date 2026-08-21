"""OIDC claim projection, group overflow, and exact group matching."""

from __future__ import annotations

from backend.admin.federation.assertion import ExternalAssertion, require_subject, text_claim
from backend.admin.federation.errors import SsoAssertionRejected
from backend.admin.federation.spec import AdmissionReason, OidcConfig, ProviderRecord


def groups_overflowed(claims: dict[str, object], group_claim: str) -> bool:
    if claims.get("hasgroups") is True:
        return True
    names = claims.get("_claim_names")
    return isinstance(names, dict) and group_claim in names


def assertion_from_claims(provider: ProviderRecord, claims: dict[str, object]) -> ExternalAssertion:
    config = provider.config
    subject = require_subject(claims.get("sub"))
    group_claim = config.group_claim
    overflow = groups_overflowed(claims, group_claim)
    present = group_claim in claims
    raw = claims.get(group_claim) if present else None
    groups: tuple[str, ...] = ()
    if present and not overflow:
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise SsoAssertionRejected("Groups claim must be an array of strings")
        groups = tuple(str(item) for item in raw)
    return ExternalAssertion(
        issuer=provider.issuer,
        subject=subject,
        email=text_claim(claims, "email"),
        display_name=text_claim(claims, "name"),
        preferred_username=text_claim(claims, "preferred_username"),
        groups=groups,
        groups_present=present and not overflow,
        groups_overflow=overflow,
        claims=dict(claims),
    )


def group_admission_reason(
    assertion: ExternalAssertion, config: OidcConfig
) -> AdmissionReason | None:
    if assertion.groups_overflow:
        return "group_overflow"
    if not assertion.groups_present:
        return "group_missing"
    allowed = set(config.group_allowlist)
    if allowed.isdisjoint(assertion.groups):
        return "group_not_allowed"
    return None
