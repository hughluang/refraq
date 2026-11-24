"""Project measured diagnostics, keeping validity, scope and units explicit."""

from backend.core.time import format_instant, parse_instant, utc_now
from backend.metadata.mirrors.diagnostic_schemas import RowSample, SourceReceipt
from backend.metadata.mirrors.diagnostic_store import DiagnosticStore
from backend.metadata.mirrors.errors import MirrorError

LINKS = ("replication", "production", "consumption", "storage")
SEVERITY = ("failed", "stale", "unobserved", "healthy")
METRICS = ("captured_events", "committed_events", "committed_batches", "pending_events", "pending_bytes", "position_lag")


def _fresh(value, now):
    return bool(value and parse_instant(value["observed_at"]) <= now < parse_instant(value["valid_until"]))


def _identity(authority):
    return {key: str(authority.get(key, "")) for key in (
        "binding_id", "runtime_instance_id", "owner_epoch", "capture_generation", "control_revision", "credential_revision"
    )}


def _matches(value, authority):
    return value is not None and value.get("authority") == _identity(authority)


def checks_at(state, now):
    result = []
    for link in LINKS:
        value = (state or {}).get("checks", {}).get(link)
        result.append(dict(
            link=link, health=(value["outcome"] if _fresh(value, now) else "stale") if value else "unobserved",
            observed_at=value["observed_at"] if value else None,
            valid_until=value["valid_until"] if value else None,
            last_success_at=value.get("last_success_at") if value else None,
            failure_at=value.get("failure_at") if value else None,
            error_code=value.get("error_code") if value else None,
        ))
    return result


def record_source(source_id, authority, receipt: SourceReceipt, *, store: DiagnosticStore, now=None, round_id):
    now = now or utc_now()
    identity = _identity(authority)
    if any(str(sample.capture_generation) != str(authority.get("capture_generation")) for sample in receipt.samples):
        raise ValueError("Sample capture lineage mismatch")

    def update(previous):
        state = previous if _matches(previous, authority) else dict(authority=identity, checks={}, history=(previous or {}).get("history", []))
        if any(item["id"] == round_id for item in state["history"]):
            return state
        for link, observation in receipt.checks.items():
            if observation.observed_at > now:
                raise ValueError("Future diagnostic observation")
            incoming = observation.model_dump(mode="json")
            prior = state["checks"].get(link)
            if prior and observation.observed_at <= parse_instant(prior["observed_at"]):
                continue
            incoming["last_success_at"] = (incoming["observed_at"] if observation.outcome == "healthy"
                                           else prior.get("last_success_at") if prior else None)
            incoming["failure_at"] = incoming["observed_at"] if observation.outcome == "failed" else None
            state["checks"][link] = incoming
        round_checks = {}
        for link, observation in receipt.checks.items():
            value = observation.model_dump(mode="json")
            value["last_success_at"] = value["observed_at"] if observation.outcome == "healthy" else state["checks"].get(link, {}).get("last_success_at")
            value["failure_at"] = value["observed_at"] if observation.outcome == "failed" else None
            round_checks[link] = value
        snapshot = checks_at({"checks": round_checks}, now)
        state["history"] = (state["history"] + [dict(id=round_id, at=format_instant(now), checks=snapshot,
                              health=min((c["health"] for c in snapshot), key=SEVERITY.index))])[-16:]
        state["last_checked_at"] = format_instant(now)
        return state

    store.update("source", source_id, update)
    for sample in receipt.samples:
        value = dict(authority=identity, **sample.model_dump(mode="json"))
        store.update("sample", sample.mirror_id, lambda old: value if not old or
                     parse_instant(value["observed_at"]) > parse_instant(old["observed_at"]) else old)


def record_rows(mirror_id, sample: RowSample, *, store: DiagnosticStore):
    value = sample.model_dump(mode="json")
    store.update("rows", mirror_id, lambda old: value if not old or parse_instant(value["observed_at"]) > parse_instant(old["observed_at"]) else old)


def record_runtime(runtime_id, kind, value, *, store: DiagnosticStore):
    if kind not in {"heartbeat", "cycle", "assignment"}:
        raise ValueError("Unknown runtime observation")
    def update(old):
        if old and parse_instant(value["observed_at"]) < parse_instant(old["observed_at"]):
            return old
        if kind == "cycle":
            return {**value, "last_completed_at": value.get("completed_at") or value.get("last_completed_at") or (old or {}).get("last_completed_at"),
                    "last_duration_seconds": value.get("duration_seconds") if value.get("completed_at") else
                    value.get("last_duration_seconds", (old or {}).get("last_duration_seconds"))}
        return value
    store.update("runtime_" + kind, runtime_id, update)


def mirror_measurements(mirror_id, *, store: DiagnosticStore, read_scope, read_detail, now=None):
    now = now or utc_now()
    detail = read_detail(mirror_id)["mirror"]
    _, bindings = read_scope()
    sample = _sample_for(detail, bindings, store.read("sample", mirror_id), now)
    rows = store.read("rows", mirror_id)
    if not rows or rows["generation_id"] != detail["published_generation_id"]:
        rows = None
    source = _source(detail["source_id"], [detail], bindings, now, store=store)
    return dict(mirror_id=mirror_id, source_id=detail["source_id"], sample=sample,
                row_sample=rows, row_sample_stale=bool(rows and not _fresh(rows, now)),
                estimated_rows=detail["estimated_rows"], published_generation_id=detail["published_generation_id"],
                runtime_instance_id=source["runtime_instance_id"], last_source_check_at=source["last_checked_at"],
                end_of_cycle_wait_seconds=source["end_of_cycle_wait_seconds"])


def _sample_for(mirror, bindings, sample, now):
    authority = bindings.get(mirror["source_id"], {})
    if not _matches(sample, authority):
        return None
    if sample["generation_id"] not in {mirror.get("published_generation_id"), mirror.get("allocated_generation_id")}:
        return None
    value = {key: item for key, item in sample.items() if key != "authority"}
    if sample["generation_id"] != mirror.get("published_generation_id"):
        value["freshness_ms"] = None
        value["checkpoint_ref"] = None
    return {**value, "stale": not _fresh(sample, now)}


def _source(source_id, mirrors, bindings, now, *, store: DiagnosticStore):
    authority = bindings.get(source_id, {})
    state = store.read("source", source_id)
    if not _matches(state, authority):
        state = None
    runtime_id = authority.get("runtime_instance_id")
    assignment = store.read("runtime_assignment", runtime_id) if runtime_id else None
    checks = checks_at(state, now)
    name = mirrors[0]["source_name"] if mirrors else source_id
    return dict(id=source_id, name=name, runtime_instance_id=runtime_id,
                health=min((c["health"] for c in checks), key=SEVERITY.index), checks=checks,
                history=[None] * (16 - len((state or {}).get("history", []))) + (state or {}).get("history", []),
                last_checked_at=(state or {}).get("last_checked_at"),
                end_of_cycle_wait_seconds=(assignment or {}).get("end_of_cycle_wait_seconds"))


def read_diagnostics(*, store: DiagnosticStore, read_scope, source_id=None, runtime_id=None, source_offset=0, runtime_offset=0, assignment_offset=0, q=None, now=None):
    now = now or utc_now()
    mirrors, bindings = read_scope()
    assignments = store.all("runtime_assignment")
    scope = [m for m in mirrors if (source_id is None or m["source_id"] == source_id) and
             (runtime_id is None or bindings.get(m["source_id"], {}).get("runtime_instance_id") == runtime_id)]
    if source_id and not scope and source_id not in bindings:
        raise MirrorError("MIRROR_NOT_FOUND", 404)
    grouped = {}
    if source_id:
        grouped[source_id] = []
    for mirror in scope:
        grouped.setdefault(mirror["source_id"], []).append(mirror)
    sources = [_source(sid, rows, bindings, now, store=store) for sid, rows in sorted(grouped.items())]
    samples = store.all("sample")
    summary = {}
    for metric in METRICS:
        values = []
        for mirror in scope:
            value = _sample_for(mirror, bindings, samples.get(mirror["id"]), now)
            if value and not value["stale"] and value[metric] is not None:
                values.append(value)
        summary[metric] = dict(value=sum(s[metric] for s in values) if values else None,
                               sampled=len(values), missing=len(scope) - len(values),
                               interval_start=min((s["interval_start"] for s in values), default=None),
                               interval_end=max((s["interval_end"] for s in values), default=None),
                               oldest_observation=min((s["observed_at"] for s in values), default=None),
                               newest_observation=max((s["observed_at"] for s in values), default=None))
    states = {kind: {key: 0 for key in ("active", "idle", "blocked", "unobserved")} for kind in ("capture", "write")}
    intervals = []
    for mirror in scope:
        sample = _sample_for(mirror, bindings, samples.get(mirror["id"]), now)
        for kind in states:
            state = sample[kind + "_state"] if sample and not sample["stale"] else "unobserved"
            states[kind][state] += 1
        intervals.append(dict(mirror_id=mirror["id"], qualified_table=mirror["qualified_table"],
                              interval_start=sample["interval_start"] if sample else None,
                              interval_end=sample["interval_end"] if sample else None,
                              observed_at=sample["observed_at"] if sample else None,
                              stale=sample["stale"] if sample else False))
    matching_runtime_ids = {s["runtime_instance_id"] for s in sources if s["runtime_instance_id"]}
    runtimes = []
    for rid in sorted(matching_runtime_ids):
        assignment = assignments.get(rid)
        heartbeat = store.read("runtime_heartbeat", rid)
        cycle = store.read("runtime_cycle", rid)
        assigned = [sid for sid in (assignment or {}).get("source_ids", [])
                    if bindings.get(sid, {}).get("runtime_instance_id") == rid]
        assigned_offset = assignment_offset if assignment_offset < len(assigned) else 0
        runtimes.append(dict(id=rid, heartbeat=heartbeat, heartbeat_health="healthy" if _fresh(heartbeat, now) else
                             "stale" if heartbeat else "unobserved", cycle=cycle,
                             cycle_health="healthy" if _fresh(cycle, now) else "stale" if cycle else "unobserved",
                             end_of_cycle_wait_seconds=(assignment or {}).get("end_of_cycle_wait_seconds"),
                             assignment_stale=not _fresh(assignment, now),
                             source_ids=assigned[assigned_offset:assigned_offset + 8], assignment_offset=assigned_offset,
                             total_sources=len(assigned)))
    filtered = [s for s in sources if not q or q.casefold() in (s["name"] + s["id"]).casefold()]
    return dict(observed_at=format_instant(now), mirror_count=len(scope), source_count=len(sources),
                sources=filtered[source_offset:source_offset + 8], matching_sources=len(filtered),
                source_offset=source_offset, runtimes=runtimes[runtime_offset:runtime_offset + 3],
                runtime_offset=runtime_offset, assignment_offset=assignment_offset, total_runtimes=len(runtimes),
                summary=summary, states=states, intervals=intervals,
                link_counts={health: sum(c["health"] == health for s in sources for c in s["checks"]) for health in SEVERITY})
