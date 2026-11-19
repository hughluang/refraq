"""Pinned deployment signing trust, with exact operation and resource scopes."""

import math

import jwt

from backend.metadata.capture.runtime_store import RuntimeBlocked


class SignedAuthority:
    def __init__(self, *, keys, issuer, audience):
        if not keys or not issuer or not audience:
            raise RuntimeBlocked("explicit_signing_trust_required")
        self.keys = dict(keys)
        self.issuer = issuer
        self.audience = audience

    def verify(self, token, *, purpose, authority, scope, operation_id):
        try:
            header = jwt.get_unverified_header(token)
            claims = jwt.decode(
                token, self.keys[header["kid"]], algorithms=["EdDSA"],
                issuer=self.issuer, audience=self.audience,
                options={"require": ["exp", "iat", "nbf", "jti", "iss", "aud"]},
            )
            if (any(type(claims[key]) not in {int, float} or not math.isfinite(claims[key])
                    for key in ("exp", "iat", "nbf"))
                    or not claims["iat"] <= claims["nbf"] < claims["exp"]
                    or claims.get("purpose") != purpose or claims.get("authority") != authority
                    or claims.get("scope") != scope
                    or claims.get("operation_id") != operation_id
                    or not isinstance(claims["jti"], str) or not claims["jti"]
                    or claims["exp"] - claims["iat"] > 3600):
                raise ValueError()
            return claims
        except (jwt.PyJWTError, KeyError, TypeError, ValueError):
            raise RuntimeBlocked("signed_authority_unverified") from None
