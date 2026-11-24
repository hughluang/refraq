"""Reconciled fleet Overview, Inventory and health navigation reads."""

from contextlib import contextmanager

from backend.core.time import format_instant, utc_now
from backend.metadata.mirrors import presentation
from backend.metadata.mirrors.lifecycle import dispatch_scope, open_evidence, registry_scope


@contextmanager
def _read(store, mirror_store, source_store, catalog_store, now):
    with mirror_store.transaction() as session:
        mirror_store.isolate_read(session)
        yield mirror_store.fleet(store, source_store=source_store, catalog_store=catalog_store, now=now), session


def inventory(*, store, mirror_store, source_store, catalog_store, now=None, **query):
    now = now or utc_now()
    with _read(store, mirror_store, source_store, catalog_store, now) as (fleet, session):
        rows, total, facets = fleet.inventory_page(session, **query)
        contexts = {sid: presentation.source_lifecycle(mirror_store, session, sid) for sid in {r["source_id"] for r in rows}}
        items = []
        for row in rows:
            item = presentation.present(mirror_store, session, row["state"], contexts[row["source_id"]])
            item.update({key: row[key] for key in ("grouped_state", "attention_cause", "attention_since",
                                                   "source_size_bytes", "estimated_rows")})
            items.append(item)
        return dict(items=items, total=total, cause_counts=facets, limit=query.get("limit", 100), offset=query.get("offset", 0))


def sources(*, store, mirror_store, source_store, catalog_store, now=None, **query):
    with _read(store, mirror_store, source_store, catalog_store, now or utc_now()) as (fleet, session):
        items, total = fleet.source_page(session, **query)
        return dict(items=items, total=total, limit=query.get("limit", 12), offset=query.get("offset", 0))


def runtimes(*, store, mirror_store, source_store, catalog_store, now=None, **query):
    with _read(store, mirror_store, source_store, catalog_store, now or utc_now()) as (fleet, session):
        items, total = fleet.runtime_page(session, **query)
        return dict(items=items, total=total, limit=query.get("limit", 12), offset=query.get("offset", 0))


def _snapshot_total(fleet, session, **scope):
    rows = fleet.scans(session, **scope)
    mirrors, bindings, operations = fleet.scan_context(session, rows)
    grouped = {}
    for mirror in mirrors:
        grouped.setdefault(mirror["source_id"], []).append(mirror)
    scopes = {sid: dispatch_scope(registry_scope(values), bindings.get(sid, {}), operations) for sid, values in grouped.items()}
    scanned, size, sampled = 0, 0, 0
    for row in rows:
        evidence = open_evidence(row["state"], operations.get(row["id"], []), bindings.get(row["source_id"], {}), scopes[row["source_id"]])
        progress = presentation.snapshot_progress(evidence.snapshot, evidence.stage)
        if progress and progress["scanned_bytes"] is not None and progress["bytes_observed_at"] is not None and row["source_size_bytes"] is not None:
            scanned += progress["scanned_bytes"]
            size += row["source_size_bytes"]
            sampled += 1
    return dict(scanned_bytes=scanned if sampled else None, source_size_bytes=size if sampled else None,
                sampled=sampled, missing=len(rows) - sampled, queued=fleet.queued(session, **scope))


def overview(*, store, mirror_store, source_store, catalog_store, source_id=None, runtime_id=None, rank="size", now=None):
    now = now or utc_now()
    scope = dict(source_id=source_id, runtime_id=runtime_id)
    with _read(store, mirror_store, source_store, catalog_store, now) as (fleet, session):
        totals = fleet.totals(session, **scope)
        health = fleet.health_totals(session, **scope)
        ranking, ranking_total = fleet.source_page(session, rank=rank, limit=8, **scope)
        snapshot = _snapshot_total(fleet, session, **scope)
        count = totals["mirror_count"]
        states = {state: dict(count=value, percent=100 * value / count if count else None)
                  for state, value in totals["states"].items()}
        return {**totals, **health, "observed_at": format_instant(now), "states": states,
            "published_percent": 100 * totals["published_count"] / count if count else None,
            "attention_count": states["attention"]["count"], "snapshot": snapshot,
            "ranking": ranking, "ranking_total": ranking_total}
