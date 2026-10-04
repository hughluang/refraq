"""Choose the site schedule timezone from pre-upgrade cron commitment zones.

Interval rows are not inputs. The caller passes only cron commitment zones.
"""

from __future__ import annotations

from backend.core.time_zones import canonical_zone_id

__all__ = ["CommitmentZonesDisagree", "parameter_row_for_commitment_zones"]


class CommitmentZonesDisagree(RuntimeError):
    """Cron rows do not share one current zone id."""


def parameter_row_for_commitment_zones(
    zones: list[str],
    *,
    parameter_present: bool,
) -> tuple[str, str] | None:
    """Return ``(value, source)`` to insert, or None when the row should stay absent.

    ``source`` is ``seed`` only for ``UTC``. Any other single current id is ``user``
    so a later reset still restores the product seed. An existing parameter row is
    not overwritten. Several current ids, or a zone that is not a current id or
    alias, raise ``CommitmentZonesDisagree``.
    """
    unrecognized: set[str] = set()
    canonical: set[str] = set()
    for raw in zones:
        canon = canonical_zone_id(raw)
        if canon is None:
            unrecognized.add(raw)
            continue
        canonical.add(canon)
    if unrecognized or len(canonical) > 1:
        parts: list[str] = []
        if unrecognized:
            parts.append("unrecognized: " + ", ".join(sorted(unrecognized)))
        if len(canonical) > 1:
            parts.append("zones: " + ", ".join(sorted(canonical)))
        raise CommitmentZonesDisagree(
            "schedule_timezone cannot be folded from cron commitment zones; "
            + "; ".join(parts)
        )
    if not canonical or parameter_present:
        return None
    zone = next(iter(canonical))
    source = "seed" if zone == "UTC" else "user"
    return zone, source
