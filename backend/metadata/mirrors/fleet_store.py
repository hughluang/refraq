"""Fleet persistence projections with database filtering, counting and paging."""

from copy import deepcopy

from sqlalchemy import DateTime, String, Text, and_, case, cast, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from backend.core.time import format_instant, parse_instant
from backend.metadata.mirrors.diagnostic_store import DiagnosticRow
from backend.metadata.mirrors.diagnostics import LINKS, SEVERITY, _matches, checks_at
from backend.metadata.mirrors.lifecycle import current_open, dispatch_scope, open_evidence, registry_scope
from backend.metadata.mirrors.models import MirrorOperationRow, MirrorRow
from backend.metadata.mirrors.store import MemoryMirrorStore
from backend.metadata.models import CatalogObjectRow, SourceCaptureBindingRow, SourceRow

STATES = ("synchronizing", "copying", "attention", "stopped")
CAUSES = ("schema", "permission", "continuity", "pending_stop", "source_prerequisite", "snapshot_evidence")
UNASSIGNED = "unassigned"


def _array_contains(session, expression, value):
    if session.get_bind().dialect.name == "postgresql":
        array = cast(expression, JSONB)
        values = func.jsonb_array_elements_text(case((func.jsonb_typeof(array) == "array", array),
                                                    else_=cast(literal("[]"), JSONB))).table_valued("value").alias()
    else:
        values = func.json_each(expression).table_valued("value").alias()
    return exists(select(1).select_from(values).where(values.c.value == value))


def _source_blocked(source, binding, mirror):
    if source is not None and (source.status == "disabled" or not source.capture_credential_ciphertext):
        return True
    owner = binding.get("allocation", {}).get("command", {})
    scope = binding.get("allocation", {}).get("scope") or owner.get("replacement", {}).get("scope", {})
    approved = scope.get("profile", {}).get("tables")
    return bool(owner and approved is not None and all(owner.get(key) == binding.get(key) for key in (
        "source_id", "owner_epoch", "runtime_instance_id", "capture_generation"
    )) and mirror["qualified_table"] not in approved)


def _classification(mirror, status, source_blocked, operations):
    if not mirror["enabled"]:
        control = mirror["control"]
        ack = control.get("stop_ack") or {}
        confirmed = status == "disabled" and ack.get("observed_at") and ack["observed_at"] == control.get("observed_at") and any(
            op["kind"] == "disable" and op["state"] == "applied" and op["id"] == ack.get("operation_id") and
            op["control_revision"] == control["control_revision"] == control.get("applied_revision") and
            ack.get("source_operation_id") in op["observed_evidence_refs"] for op in operations)
        return ("stopped", None) if confirmed else ("attention", "pending_stop")
    blocker = (mirror.get("blocker") or {}).get("cause")
    if blocker in {"schema", "permission", "continuity"}:
        return "attention", blocker
    if source_blocked or status == "source_fault":
        return "attention", "source_prerequisite"
    if status == "needs_attention":
        return "attention", "snapshot_evidence"
    if status == "ready" and mirror.get("published_generation_id"):
        return "synchronizing", None
    return "copying", None


def _metric(rows, name):
    values = [row[name] for row in rows if row[name] is not None]
    return dict(value=sum(values) if values else None, sampled=len(values), missing=len(rows) - len(values))


class FleetStore:
    def __init__(self, mirror_store, diagnostic_store, *, source_store, catalog_store, now):
        self.mirrors = mirror_store
        self.diagnostics = diagnostic_store
        self.sources = source_store
        self.catalog = catalog_store
        self.now = now
        self._rows = None

    def _memory_rows(self, session):
        if self._rows is not None:
            return self._rows
        sources = {s.id: s for s in self.sources.list_sources()[0]}
        bindings = self.sources.capture_bindings
        observations = self.diagnostics.all("source")
        operations = {}
        for operation in session.operations.values():
            operations.setdefault(operation["mirror_id"], []).append(operation)
        grouped = {}
        for mirror in session.mirrors.values():
            grouped.setdefault(mirror["source_id"], []).append(mirror)
        result = []
        for sid, mirrors in grouped.items():
            binding = bindings.get(sid, {})
            source = sources.get(sid)
            desired = registry_scope(mirrors)
            scope = dispatch_scope(desired, binding, operations)
            observation = observations.get(sid)
            checks = checks_at(observation if _matches(observation, binding) else None, self.now)
            segments = {c["link"]: c["health"] for c in checks}
            health = min(segments.values(), key=SEVERITY.index)
            for mirror in mirrors:
                ops = operations.get(mirror["id"], [])
                status = open_evidence(mirror, ops, binding, scope).status
                state, cause = _classification(mirror, status, _source_blocked(source, binding, mirror), ops)
                requests = [op["requested_at"] for op in ops
                            if op["control_revision"] == mirror["control"]["control_revision"]]
                since = (mirror.get("blocker") or {}).get("since")
                if not since and cause:
                    since = min(requests) if requests else mirror["control"].get("observed_at")
                opened = current_open(mirror, ops) or {}
                queued_copy = state == "copying" and status not in {"snapshotting", "catching_up"} and (
                    mirror.get("published_generation_id") is None or status == "rebuilding" or any(
                        opened.get(key) is not None for key in ("reopen_baseline", "replacement_generation_id", "interrupted_partition")))
                obj = self.catalog.get_object(mirror["object_id"])
                result.append(dict(id=mirror["id"], source_id=sid, source_name=source.name if source else mirror["source_name"],
                    source_key=source.key if source else mirror["source_key"], qualified_table=mirror["qualified_table"],
                    runtime_instance_id=binding.get("runtime_instance_id") or None, status=status,
                    grouped_state=state, attention_cause=cause, attention_since=since, queued_copy=queued_copy,
                    source_size_bytes=obj.source_size_bytes if obj else None,
                    estimated_rows=obj.estimated_rows if obj else None,
                    published=mirror.get("published_generation_id") is not None, state=deepcopy(mirror),
                    health=health, **segments))
        self._rows = result
        return result

    def _relation(self, session):
        mirror, binding, observation = MirrorRow.state, SourceCaptureBindingRow.state, DiagnosticRow.value
        status = MirrorRow.effective_status
        control = mirror["control"]
        revision = control["control_revision"].as_integer()
        command = MirrorOperationRow.command
        stop = control["stop_ack"]
        confirmed = func.coalesce(and_(status == "disabled", control["applied_revision"].as_integer() == revision,
            stop["observed_at"].as_string() == control["observed_at"].as_string(),
            exists(select(1).where(MirrorOperationRow.mirror_id == MirrorRow.id,
                command["kind"].as_string() == "disable", command["state"].as_string() == "applied",
                MirrorOperationRow.id == stop["operation_id"].as_string(),
                command["control_revision"].as_integer() == revision,
                _array_contains(session, command["observed_evidence_refs"], stop["source_operation_id"].as_string())))), False)
        owner = binding["allocation"]["command"]
        approved = func.coalesce(func.nullif(cast(binding["allocation"]["scope"]["profile"]["tables"], Text), "null"),
                                 func.nullif(cast(owner["replacement"]["scope"]["profile"]["tables"], Text), "null"))
        current_owner = and_(*(owner[key].as_string() == binding[key].as_string() for key in (
            "source_id", "owner_epoch", "runtime_instance_id", "capture_generation")))
        unqualified = and_(current_owner, approved.is_not(None), cast(approved, Text) != "null",
                          ~_array_contains(session, approved, mirror["qualified_table"].as_string()))
        prerequisite = or_(SourceRow.status == "disabled", SourceRow.capture_credential_ciphertext.is_(None),
                           SourceRow.capture_credential_ciphertext == "", unqualified, status == "source_fault")
        blocker = mirror["blocker"]["cause"].as_string()
        cause = case((and_(~MirrorRow.enabled, ~confirmed), literal("pending_stop")),
            (and_(MirrorRow.enabled, blocker.in_(("schema", "permission", "continuity"))), blocker),
            (and_(MirrorRow.enabled, prerequisite), literal("source_prerequisite")),
            (and_(MirrorRow.enabled, status == "needs_attention"), literal("snapshot_evidence")), else_=None)
        grouped = case((cause.is_not(None), "attention"), (~MirrorRow.enabled, "stopped"),
            (and_(status == "ready", mirror["published_generation_id"].as_string().is_not(None)), "synchronizing"),
            else_="copying")
        requested = select(func.min(command["requested_at"].as_string())).where(
            MirrorOperationRow.mirror_id == MirrorRow.id, command["control_revision"].as_integer() == revision).scalar_subquery()
        replacement = exists(select(1).where(MirrorOperationRow.mirror_id == MirrorRow.id,
            command["kind"].as_string() == "open", command["state"].as_string() == "pending",
            command["control_revision"].as_integer() == revision,
            or_(*(command[key].as_string().is_not(None) for key in ("reopen_baseline", "replacement_generation_id", "interrupted_partition")))))
        queued_copy = and_(grouped == "copying", status.not_in(("snapshotting", "catching_up")),
            or_(mirror["published_generation_id"].as_string().is_(None), status == "rebuilding", replacement))
        since = case((cause.is_not(None), func.coalesce(mirror["blocker"]["since"].as_string(), requested,
                                                       control["observed_at"].as_string())), else_=None)
        current = and_(*(observation["authority"][key].as_string() ==
                         func.coalesce(cast(binding[key].as_string(), String), "") for key in (
            "binding_id", "runtime_instance_id", "owner_epoch", "capture_generation", "control_revision", "credential_revision")))
        checks = {}
        for link in LINKS:
            check = observation["checks"][link]
            observed, valid = check["observed_at"].as_string(), check["valid_until"].as_string()
            if session.get_bind().dialect.name == "postgresql":
                fresh = and_(cast(observed, DateTime(timezone=True)) <= self.now,
                             cast(valid, DateTime(timezone=True)) > self.now)
            else:
                fresh = and_(func.julianday(observed) <= func.julianday(format_instant(self.now)),
                             func.julianday(valid) > func.julianday(format_instant(self.now)))
            checks[link] = case((and_(current, check["outcome"].as_string().is_not(None)),
                case((fresh, check["outcome"].as_string()), else_="stale")), else_="unobserved")
        health = case(*[(or_(*(value == h for value in checks.values())), h) for h in SEVERITY[:-1]], else_="healthy")
        return select(MirrorRow.id, MirrorRow.source_id, mirror.label("state"),
            SourceRow.name.label("source_name"), SourceRow.key.label("source_key"),
            mirror["qualified_table"].as_string().label("qualified_table"),
            func.nullif(binding["runtime_instance_id"].as_string(), "").label("runtime_instance_id"),
            status.label("status"), grouped.label("grouped_state"), cause.label("attention_cause"), since.label("attention_since"),
            queued_copy.label("queued_copy"),
            CatalogObjectRow.source_size_bytes, CatalogObjectRow.estimated_rows,
            mirror["published_generation_id"].as_string().is_not(None).label("published"), health.label("health"),
            *(value.label(link) for link, value in checks.items())
        ).select_from(MirrorRow).join(SourceRow, SourceRow.id == MirrorRow.source_id).outerjoin(
            CatalogObjectRow, CatalogObjectRow.id == mirror["object_id"].as_string()).outerjoin(
            SourceCaptureBindingRow, SourceCaptureBindingRow.source_id == MirrorRow.source_id).outerjoin(
            DiagnosticRow, and_(DiagnosticRow.kind == "source", DiagnosticRow.scope_id == MirrorRow.source_id)).cte("fleet_mirrors")

    def _scope(self, relation, *, source_id=None, runtime_id=None):
        conditions = []
        if source_id is not None:
            conditions.append(relation.c.source_id == source_id)
        if runtime_id is not None:
            conditions.append(relation.c.runtime_instance_id.is_(None) if runtime_id == UNASSIGNED
                              else relation.c.runtime_instance_id == runtime_id)
        return conditions

    def _memory_scope(self, rows, *, source_id=None, runtime_id=None):
        return [r for r in rows if (source_id is None or r["source_id"] == source_id) and
                (runtime_id is None or (r["runtime_instance_id"] or UNASSIGNED) == runtime_id)]

    def inventory_page(self, session, *, source_id=None, runtime_id=None, status=None, grouped_state=None,
                       published_only=False, cause=None, sort="priority", q=None, limit=100, offset=0):
        if isinstance(session, MemoryMirrorStore):
            rows = self._memory_scope(self._memory_rows(session), source_id=source_id, runtime_id=runtime_id)
            needle = (q or "").casefold()
            rows = [r for r in rows if (status is None or r["status"] == status) and
                (grouped_state is None or r["grouped_state"] == grouped_state) and (not published_only or r["published"]) and
                any(needle in r[key].casefold() for key in ("id", "qualified_table", "source_name", "source_key"))]
            facets = {c: sum(r["attention_cause"] == c for r in rows) for c in CAUSES}
            rows = [r for r in rows if cause is None or r["attention_cause"] == cause]
            def order(row):
                table = (row["qualified_table"], row["id"])
                if sort in {"size", "rows"}:
                    value = row["source_size_bytes" if sort == "size" else "estimated_rows"]
                    return (value is None, -(value or 0), *table)
                if sort == "table":
                    return table
                priority = {"attention": 0, "copying": 1, "synchronizing": 2, "stopped": 3}[row["grouped_state"]]
                triage = 2 if row["attention_cause"] == "pending_stop" else int(row["published"])
                since = parse_instant(row["attention_since"]).timestamp() if row["attention_since"] else float("inf")
                size = row["source_size_bytes"] if priority else None
                return (priority, triage if priority == 0 else 0, since if priority == 0 else 0,
                        size is None, -(size or 0), *table)
            rows.sort(key=order)
            return rows[offset:offset + limit], len(rows), facets
        relation = self._relation(session)
        columns = relation.c
        conditions = self._scope(relation, source_id=source_id, runtime_id=runtime_id)
        if status is not None:
            conditions.append(columns.status == status)
        if grouped_state is not None:
            conditions.append(columns.grouped_state == grouped_state)
        if published_only:
            conditions.append(columns.published)
        if q:
            fields = (columns.id, columns.qualified_table, columns.source_name, columns.source_key)
            if session.get_bind().dialect.name == "postgresql":
                conditions.append(or_(*(func.casefold(field.collate("pg_unicode_fast")).contains(q.casefold(), autoescape=True)
                                        for field in fields)))
            else:
                conditions.append(or_(*(field.icontains(q, autoescape=True) for field in fields)))
        facets = {c: 0 for c in CAUSES}
        facets.update(dict(session.execute(select(columns.attention_cause, func.count()).where(
            *conditions, columns.attention_cause.is_not(None)).group_by(columns.attention_cause)).all()))
        if cause is not None:
            conditions.append(columns.attention_cause == cause)
        table = (columns.qualified_table, columns.id)
        if sort in {"size", "rows"}:
            order = ((columns.source_size_bytes if sort == "size" else columns.estimated_rows).desc().nullslast(), *table)
        elif sort == "table":
            order = table
        else:
            priority = case(*[(columns.grouped_state == state, index) for index, state in enumerate(("attention", "copying", "synchronizing", "stopped"))])
            order = (priority, case((columns.attention_cause == "pending_stop", 2),
                                   (and_(columns.grouped_state == "attention", columns.published), 1), else_=0),
                     case((columns.grouped_state == "attention", columns.attention_since), else_=None).asc().nullslast(),
                     case((columns.grouped_state != "attention", columns.source_size_bytes), else_=None).desc().nullslast(), *table)
        total = session.scalar(select(func.count()).select_from(relation).where(*conditions))
        rows = session.execute(select(relation).where(*conditions).order_by(*order).limit(limit).offset(offset)).mappings().all()
        return [dict(r) for r in rows], total, facets

    def _sources(self, session, *, source_id=None, runtime_id=None):
        if isinstance(session, MemoryMirrorStore):
            groups = {}
            for row in self._memory_scope(self._memory_rows(session), source_id=source_id, runtime_id=runtime_id):
                groups.setdefault(row["source_id"], []).append(row)
            return [dict(id=sid, name=rows[0]["source_name"], runtime_instance_id=rows[0]["runtime_instance_id"],
                health=rows[0]["health"], segment_health={link: rows[0][link] for link in LINKS}, mirror_count=len(rows),
                attention_count=sum(r["grouped_state"] == "attention" for r in rows),
                source_size=_metric(rows, "source_size_bytes"), estimated_rows=_metric(rows, "estimated_rows"))
                for sid, rows in groups.items()]
        relation = self._relation(session)
        columns = relation.c
        dimensions = (columns.source_id, columns.source_name, columns.runtime_instance_id, columns.health,
                      *(columns[link] for link in LINKS))
        return select(*dimensions, func.count().label("mirror_count"),
            func.sum(case((columns.grouped_state == "attention", 1), else_=0)).label("attention_count"),
            func.sum(columns.source_size_bytes).label("size_value"), func.count(columns.source_size_bytes).label("size_sampled"),
            func.sum(columns.estimated_rows).label("rows_value"), func.count(columns.estimated_rows).label("rows_sampled")
        ).where(*self._scope(relation, source_id=source_id, runtime_id=runtime_id)).group_by(*dimensions).cte("fleet_sources")

    def _source_view(self, row):
        return dict(id=row["source_id"], name=row["source_name"], runtime_instance_id=row["runtime_instance_id"],
            health=row["health"], segment_health={link: row[link] for link in LINKS}, mirror_count=row["mirror_count"],
            attention_count=row["attention_count"], source_size=dict(value=row["size_value"], sampled=row["size_sampled"],
                missing=row["mirror_count"] - row["size_sampled"]), estimated_rows=dict(value=row["rows_value"],
                sampled=row["rows_sampled"], missing=row["mirror_count"] - row["rows_sampled"]))

    def source_page(self, session, *, source_id=None, runtime_id=None, q=None, health=None, segment=None, limit=12, offset=0, rank=None):
        sources = self._sources(session, source_id=source_id, runtime_id=runtime_id)
        if isinstance(sources, list):
            rows = [s for s in sources if (not q or q.casefold() in (s["id"] + " " + s["name"]).casefold()) and
                    (health is None or (s["segment_health"][segment] if segment else s["health"]) == health)]
            rows.sort(key=lambda s: (False if rank == "attention" else s["source_size"]["value"] is None,
                                    -(s["attention_count"] if rank == "attention" else s["source_size"]["value"] or 0), s["id"])
                      if rank else (SEVERITY.index(s["segment_health"][segment] if segment else s["health"]), s["id"]))
            return rows[offset:offset + limit], len(rows)
        columns = sources.c
        relevant = columns[segment] if segment else columns.health
        conditions = [relevant == health] if health else []
        if q:
            fields = (columns.source_id, columns.source_name)
            if session.get_bind().dialect.name == "postgresql":
                conditions.append(or_(*(func.casefold(field.collate("pg_unicode_fast")).contains(q.casefold(), autoescape=True) for field in fields)))
            else:
                conditions.append(or_(*(field.icontains(q, autoescape=True) for field in fields)))
        order = ((columns.attention_count if rank == "attention" else columns.size_value).desc().nullslast(), columns.source_id) if rank else (
            case(*[(relevant == value, index) for index, value in enumerate(SEVERITY)]), columns.source_id)
        total = session.scalar(select(func.count()).select_from(sources).where(*conditions))
        rows = session.execute(select(sources).where(*conditions).order_by(*order).limit(limit).offset(offset)).mappings()
        return [self._source_view(row) for row in rows], total

    def runtime_page(self, session, *, source_id=None, runtime_id=None, q=None, health=None, segment=None, limit=12, offset=0):
        sources = self._sources(session, source_id=source_id, runtime_id=runtime_id)
        if isinstance(sources, list):
            groups = {}
            for source in sources:
                groups.setdefault(source["runtime_instance_id"] or UNASSIGNED, []).append(source)
            result = []
            for rid, rows in groups.items():
                if q and q.casefold() not in rid.casefold():
                    continue
                relevant = [r["segment_health"][segment] if segment else r["health"] for r in rows]
                affected = sum(h == health for h in relevant) if health else sum(h != "healthy" for h in relevant)
                if health and not affected:
                    continue
                result.append(dict(id=rid, runtime_instance_id=None if rid == UNASSIGNED else rid,
                    source_count=len(rows), affected_source_count=affected, health=min(relevant, key=SEVERITY.index)))
            result.sort(key=lambda r: (-r["affected_source_count"], r["id"]))
            return result[offset:offset + limit], len(result)
        columns = sources.c
        relevant = columns[segment] if segment else columns.health
        rid = func.coalesce(columns.runtime_instance_id, UNASSIGNED)
        affected = func.sum(case((relevant == health if health else relevant != "healthy", 1), else_=0))
        severity = func.min(case(*[(relevant == value, index) for index, value in enumerate(SEVERITY)]))
        conditions = [rid.icontains(q, autoescape=True)] if q else []
        grouped = select(rid.label("id"), columns.runtime_instance_id, func.count().label("source_count"),
            affected.label("affected_source_count"), severity.label("severity")).where(*conditions).group_by(
                rid, columns.runtime_instance_id)
        if health:
            grouped = grouped.having(affected > 0)
        grouped = grouped.cte("fleet_runtimes")
        total = session.scalar(select(func.count()).select_from(grouped))
        rows = session.execute(select(grouped).order_by(grouped.c.affected_source_count.desc(), grouped.c.id).limit(limit).offset(offset)).mappings()
        return [dict(id=r["id"], runtime_instance_id=r["runtime_instance_id"], source_count=r["source_count"],
                     affected_source_count=r["affected_source_count"], health=SEVERITY[r["severity"]]) for r in rows], total

    def totals(self, session, *, source_id=None, runtime_id=None):
        if isinstance(session, MemoryMirrorStore):
            rows = self._memory_scope(self._memory_rows(session), source_id=source_id, runtime_id=runtime_id)
            return dict(mirror_count=len(rows), source_size=_metric(rows, "source_size_bytes"),
                estimated_rows=_metric(rows, "estimated_rows"), published_count=sum(r["published"] for r in rows),
                states={s: sum(r["grouped_state"] == s for r in rows) for s in STATES})
        relation = self._relation(session)
        columns = relation.c
        row = session.execute(select(func.count().label("count"), func.sum(columns.source_size_bytes).label("size"),
            func.count(columns.source_size_bytes).label("size_sampled"), func.sum(columns.estimated_rows).label("rows"),
            func.count(columns.estimated_rows).label("rows_sampled"),
            func.sum(case((columns.published, 1), else_=0)).label("published"),
            *(func.sum(case((columns.grouped_state == state, 1), else_=0)).label(state) for state in STATES)
        ).where(*self._scope(relation, source_id=source_id, runtime_id=runtime_id))).mappings().one()
        return dict(mirror_count=row["count"], source_size=dict(value=row["size"], sampled=row["size_sampled"],
            missing=row["count"] - row["size_sampled"]), estimated_rows=dict(value=row["rows"], sampled=row["rows_sampled"],
            missing=row["count"] - row["rows_sampled"]), published_count=row["published"] or 0,
            states={state: row[state] or 0 for state in STATES})

    def health_totals(self, session, *, source_id=None, runtime_id=None):
        sources = self._sources(session, source_id=source_id, runtime_id=runtime_id)
        if isinstance(sources, list):
            return dict(source_count=len(sources), health={h: sum(s["health"] == h for s in sources) for h in SEVERITY},
                segments={link: {h: sum(s["segment_health"][link] == h for s in sources) for h in SEVERITY} for link in LINKS})
        row = session.execute(select(func.count().label("count"),
            *(func.sum(case((sources.c.health == health, 1), else_=0)).label(health) for health in SEVERITY),
            *(func.sum(case((sources.c[link] == health, 1), else_=0)).label(link + "_" + health) for link in LINKS for health in SEVERITY)
        )).mappings().one()
        return dict(source_count=row["count"], health={h: row[h] or 0 for h in SEVERITY},
            segments={link: {h: row[link + "_" + h] or 0 for h in SEVERITY} for link in LINKS})

    def scans(self, session, *, source_id=None, runtime_id=None):
        if isinstance(session, MemoryMirrorStore):
            rows = self._memory_scope(self._memory_rows(session), source_id=source_id, runtime_id=runtime_id)
            return [r for r in rows if r["status"] in {"snapshotting", "catching_up"} and r["grouped_state"] == "copying"]
        relation = self._relation(session)
        return [dict(r) for r in session.execute(select(relation).where(*self._scope(relation, source_id=source_id, runtime_id=runtime_id),
            relation.c.status.in_(("snapshotting", "catching_up")), relation.c.grouped_state == "copying")).mappings()]

    def queued(self, session, *, source_id=None, runtime_id=None):
        if isinstance(session, MemoryMirrorStore):
            return sum(r["queued_copy"] for r in self._memory_scope(self._memory_rows(session), source_id=source_id, runtime_id=runtime_id))
        relation = self._relation(session)
        return session.scalar(select(func.count()).select_from(relation).where(
            *self._scope(relation, source_id=source_id, runtime_id=runtime_id), relation.c.queued_copy))

    def scan_context(self, session, rows):
        source_ids = {r["source_id"] for r in rows}
        if not source_ids:
            return [], {}, {}
        if isinstance(session, MemoryMirrorStore):
            mirrors = [m for m in session.mirrors.values() if m["source_id"] in source_ids]
            bindings = {sid: self.sources.capture_bindings.get(sid, {}) for sid in source_ids}
            operations = self.mirrors.pending_opens(session, {m["id"] for m in mirrors})
        else:
            mirrors = list(session.scalars(select(MirrorRow.state).where(MirrorRow.source_id.in_(source_ids))))
            bindings = {r.source_id: r.state for r in session.scalars(select(SourceCaptureBindingRow).where(
                SourceCaptureBindingRow.source_id.in_(source_ids)))}
            operations = self.mirrors.pending_opens(session, {m["id"] for m in mirrors})
        return mirrors, bindings, operations
