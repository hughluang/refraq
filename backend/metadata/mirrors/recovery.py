"""Durable, fail-closed recovery without a second target effects writer."""

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import json
from random import SystemRandom
from uuid import uuid4

from sqlalchemy import select

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.metadata.capture.configuration import SnapshotWindow, snapshot_dispatch_allowed
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.recovery_store import RecoveryRow, lock_source
from backend.metadata.mirrors.service import MirrorError


__all__ = ["Recovery", "RuntimeDispatchAdapter", "bind_recovery", "request_recovery"]


def schema_resume_allowed(evidence):
    if not isinstance(evidence, dict) or evidence.get("fingerprint_verified") is not True:
        return False
    if evidence.get("change") == "unchanged":
        return True
    return evidence.get("change") in {"add", "widen"} and all(
        evidence.get(key) is True for key in ("mapping_qualified", "detection_verified", "backfill_verified"))


def state_only_graph(graph, *, qualify_node):
    """A closed structural allowlist plus current per-node semantic authorization."""
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list) or not graph["nodes"]:
        return False
    nodes = graph["nodes"]
    ids = [node.get("id") for node in nodes if isinstance(node, dict)]
    if len(ids) != len(nodes) or any(not isinstance(key, str) or not key for key in ids) or len(set(ids)) != len(ids):
        return False
    writes = 0
    for node in nodes:
        kind = node.get("type")
        if kind not in {"trigger.manual", "read.mirror", "write.entity"} or node.get("parent_id") is not None:
            return False
        if qualify_node(node) is not True:
            return False
        writes += kind == "write.entity"
    edges = graph.get("edges")
    if not isinstance(edges, list) or not writes:
        return False
    incoming = {key: 0 for key in ids}
    outgoing = {key: [] for key in ids}
    for edge in edges:
        if not isinstance(edge, dict) or edge.get("source") not in incoming or edge.get("target") not in incoming:
            return False
        outgoing[edge["source"]].append(edge["target"])
        incoming[edge["target"]] += 1
    ready = [key for key, count in incoming.items() if count == 0]
    visited = 0
    while ready:
        key = ready.pop()
        visited += 1
        for target in outgoing[key]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    return visited == len(nodes)


class RuntimeDispatchAdapter:
    """Bridge to a trusted runtime journal; acceptance is never completion evidence.

    The runtime must durably deduplicate operation ids, build isolated empty
    generations using Application, and keep the Source busy until Publication
    confirms the committed pointer. It must not publish or release old pins here.
    """

    def __init__(self, runtime=None):
        self.runtime = runtime

    def inspect(self, **kwargs):
        if self.runtime is None:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
        return self.runtime.inspect(**kwargs)

    def submit(self, **command):
        if self.runtime is None:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
        receipt = self.runtime.submit(**command)
        if not isinstance(receipt, dict) or any(receipt.get(key) != command[key] for key in (
            "operation_id", "capture_generation", "generation_id")) or receipt.get("state") != "accepted":
            raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)


class Recovery:
    def __init__(self, *, session_factory, history, runtime=None, clock=utc_now,
                 retry_delays, audit=persist_audit_event, classifier=None, jitter=None, publication=None):
        if not retry_delays or any(type(delay) is not int or delay <= 0 for delay in retry_delays):
            raise ValueError("An approved bounded retry budget is required")
        self.session_factory = session_factory
        self.history = history
        self.runtime = runtime or RuntimeDispatchAdapter()
        self.clock = clock
        self.retry_delays = tuple(retry_delays)
        self.audit = audit
        self.classifier = classifier
        self.publication = publication
        self.jitter = jitter or SystemRandom().uniform

    def _mirror(self, session, mirror_id):
        mirror = session.get(MirrorRow, mirror_id)
        if mirror is None:
            raise MirrorError("MIRROR_NOT_FOUND", 404)
        source = lock_source(session, mirror.source_id)
        session.refresh(mirror)
        return mirror, source

    def _gate(self, session, mirror_id):
        gate = session.scalar(select(HistoryGateRow).where(HistoryGateRow.mirror_id == mirror_id)
                              .with_for_update().execution_options(populate_existing=True))
        if gate is None:
            raise MirrorError("MIRROR_HISTORY_INVALID", 409)
        return gate

    def request_recovery(self, mirror_id, *, action, expected_history_epoch, actor_user_id,
                         actor_token_id=None, reason=None, channel_id=None, channel_version=None):
        if action not in {"retry", "run_now", "postpone", "manual", "reconcile_state"} or not actor_user_id:
            raise MirrorError("REQUEST_INVALID", 422)
        if reason is not None and (not isinstance(reason, str) or len(reason) > 1000):
            raise MirrorError("REQUEST_INVALID", 422)
        if action in {"run_now", "postpone", "manual", "reconcile_state"} and not (reason or "").strip():
            raise MirrorError("REQUEST_INVALID", 422)
        if (action == "reconcile_state" and (not channel_id or type(channel_version) is not int or channel_version < 1)) or (
            action != "reconcile_state" and (channel_id is not None or channel_version is not None)):
            raise MirrorError("REQUEST_INVALID", 422)
        request = dict(action=action, expected_history_epoch=str(expected_history_epoch), reason=reason,
                       channel_id=channel_id, channel_version=channel_version,
                       actor_user_id=actor_user_id, actor_token_id=actor_token_id)
        identity = sha256(json.dumps(dict(request, mirror_id=mirror_id), sort_keys=True).encode()).hexdigest()
        with self.session_factory() as session, session.begin():
            _, source = self._mirror(session, mirror_id)
            gate = self._gate(session, mirror_id)
            if gate.history_epoch != str(expected_history_epoch):
                raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
            scoped_rows = select(RecoveryRow).where(
                RecoveryRow.source_id == source.id, RecoveryRow.mirror_id == mirror_id)
            previous = session.scalar(scoped_rows.where(RecoveryRow.identity == identity))
            rows = ()
            if previous is None:
                rows = session.scalars(scoped_rows).all()
                previous = next((row for row in rows if identity in row.journal.get("request_identities", [])), None)
            if previous is not None:
                replacement_epoch = previous.journal.get("replacement_epoch")
                if replacement_epoch and replacement_epoch != gate.history_epoch:
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                return dict(operation_id=previous.operation_id, state="pending")
            if action == "reconcile_state":
                self._classify(session, mirror_id, request)

            operation_id = None
            active_rows = [row for row in rows if row.journal["state"] not in {"applied", "superseded"}]
            if active_rows:
                [active] = active_rows
                journal = active.journal
                state = journal["state"]
                if journal.get("submission_uncertain") or state == "dispatched":
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                replacement_epoch = journal.get("replacement_epoch")
                if replacement_epoch and action != "reconcile_state":
                    if replacement_epoch != gate.history_epoch:
                        raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                    identities = list(dict.fromkeys([*journal.get("request_identities", []), active.identity, identity]))
                    active.journal = dict(journal, request=request, state="invalidated", attempts=0,
                                          next_attempt_at=None, request_identities=identities)
                    active.identity = identity
                    operation_id = active.operation_id
                elif state == "invalidated":
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                else:
                    active.journal = dict(journal, state="superseded")
            if operation_id is None:
                operation_id = "mrec_" + uuid4().hex
                session.add(RecoveryRow(operation_id=operation_id, source_id=source.id, mirror_id=mirror_id,
                                        identity=identity, journal=dict(request=request, state="pending", attempts=0,
                                        next_attempt_at=None, fault_code=None, capture_generation=None, generation_id=None)))
            self.audit(session=session, actor_user_id=actor_user_id, actor_token_id=actor_token_id,
                       resource_type="mirror", resource_id=mirror_id, action="mirror.recovery_request", result="success",
                       detail=dict(operation_id=operation_id, source_id=source.id, **request))
            return dict(operation_id=operation_id, state="pending")

    def _classify(self, session, mirror_id, request):
        if self.classifier is None:
            raise MirrorError("MIRROR_RECOVERY_AUTHORIZATION_REQUIRED", 409)
        scope = dict(mirror_id=mirror_id, channel_id=request["channel_id"], channel_version=request["channel_version"],
                     history_epoch=request["expected_history_epoch"], actor_user_id=request["actor_user_id"])
        graph = self.classifier.load_graph(session=session, **scope)
        if not state_only_graph(graph, qualify_node=lambda node: self.classifier.qualify_node(session=session, node=node, **scope)):
            raise MirrorError("MIRROR_RECOVERY_AUTHORIZATION_REQUIRED", 409)

    def get_operation(self, operation_id):
        with self.session_factory() as session:
            row = session.get(RecoveryRow, operation_id)
            if row is None:
                raise MirrorError("MIRROR_NOT_FOUND", 404)
            return dict(operation_id=row.operation_id, **deepcopy(row.journal))

    def publish_replacement(self, *, operation_id, authority, certificate):
        with self.session_factory() as session, session.begin():
            row = session.get(RecoveryRow, operation_id)
            if row is None:
                raise MirrorError("MIRROR_NOT_FOUND", 404)
            mirror, source = self._mirror(session, row.mirror_id)
            session.refresh(row)
            journal = deepcopy(row.journal)
            if journal["state"] == "applied":
                return journal["generation_id"]
            if journal["state"] != "dispatched" or not journal.get("replacement_epoch") or self.publication is None:
                raise MirrorError("MIRROR_PUBLICATION_BLOCKED", 409)
            gate = self._gate(session, mirror.id)
            if gate.status != "available" or gate.history_epoch != journal["replacement_epoch"]:
                raise MirrorError("MIRROR_HISTORY_INVALID", 409)
            observed = self.publication.publish_generation(operation_id=operation_id, authority=authority,
                generation_id=journal["generation_id"], certificate=certificate)
            if observed != journal["generation_id"]:
                raise MirrorError("MIRROR_PUBLICATION_BLOCKED", 409)
            journal.update(state="applied", submission_uncertain=False)
            row.journal = journal
            return observed

    def _defer(self, journal, state, now, fault=None):
        journal.update(state=state, fault_code=fault)
        attempt = journal["attempts"]
        if attempt >= len(self.retry_delays):
            journal.update(state="blocked", next_attempt_at=None)
        else:
            delay = self.retry_delays[attempt]
            journal.update(attempts=attempt + 1,
                           next_attempt_at=(now + timedelta(seconds=self.jitter(delay / 2, delay))).isoformat())

    def dispatch(self, *, operation_id):
        state = self._prepare_dispatch(operation_id=operation_id)
        if state != "submitting":
            return state
        with self.session_factory() as session, session.begin():
            row = session.get(RecoveryRow, operation_id)
            mirror, source = self._mirror(session, row.mirror_id)
            session.refresh(row)
            journal = deepcopy(row.journal)
            if journal["state"] != "submitting":
                return journal["state"]
            try:
                now = self.clock()
                evidence = self.runtime.inspect(session=session, mirror=mirror, now=now)
                command = journal["submission_command"]
                gate = self._gate(session, mirror.id)
                if (not mirror.enabled or gate.status != "available" or gate.history_epoch != command["history_epoch"]
                    or any(evidence.get(key) != value for key, value in (
                        ("source_id", source.id), ("mirror_id", mirror.id), ("table_identity", mirror.table_identity),
                        ("history_epoch", command["history_epoch"])))
                    or not evidence["observed_at"] <= now < evidence["valid_until"]
                    or any(evidence.get(key) is not True for key in ("ownership", "readiness", "resources"))
                    or not schema_resume_allowed(evidence.get("schema"))
                    or (command["kind"] == "resume" and evidence.get("validity") != "retained")):
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                window = SnapshotWindow.model_validate(source.snapshot_window) if source.snapshot_window else None
                if command["kind"] == "replacement" and journal["request"]["action"] != "run_now" and not snapshot_dispatch_allowed(window, now):
                    raise MirrorError("MIRROR_SNAPSHOT_WINDOW_CLOSED", 409)
                self.runtime.submit(**command)
                journal.update(state="dispatched", fault_code=None)
            except MirrorError as exc:
                self._defer(journal, "invalidated" if journal.get("replacement_epoch") else "unknown",
                            self.clock(), exc.code)
            row.journal = journal
            return journal["state"]

    def _prepare_dispatch(self, *, operation_id):
        """Commit the exact dispatch identity before any external acceptance is possible."""
        with self.session_factory() as session, session.begin():
            row = session.get(RecoveryRow, operation_id)
            if row is None:
                raise MirrorError("MIRROR_NOT_FOUND", 404)
            mirror, source = self._mirror(session, row.mirror_id)
            session.refresh(row)
            journal = deepcopy(row.journal)
            if journal["state"] in {"applied", "superseded", "blocked", "dispatched"}:
                return journal["state"]
            if journal["state"] == "submitting":
                journal["state"] = "invalidated" if journal.get("replacement_epoch") else "pending"
            now = self.clock()
            from_time = journal["next_attempt_at"]
            if from_time is not None and now < datetime.fromisoformat(from_time):
                return journal["state"]
            request = journal["request"]
            try:
                if journal.get("replacement_epoch"):
                    self.history.consume_invalidation(operation_id=operation_id)
                if request["action"] in {"manual", "postpone"}:
                    if not journal.get("replacement_epoch"):
                        journal["state"] = request["action"]
                    row.journal = journal
                    return request["action"]
                evidence = self.runtime.inspect(session=session, mirror=mirror, now=now)
                if not isinstance(evidence, dict) or any(evidence.get(key) != value for key, value in (
                    ("source_id", source.id), ("mirror_id", mirror.id), ("table_identity", mirror.table_identity))) or not (
                    evidence.get("observed_at") is not None and evidence.get("valid_until") is not None
                    and evidence["observed_at"] <= now < evidence["valid_until"]):
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                if journal.get("submission_uncertain") and not journal.get("replacement_epoch") and evidence.get("validity") != "retained":
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                if evidence.get("validity") == "lost" and journal["state"] != "invalidated":
                    affected = evidence.get("affected_mirror_ids")
                    if not isinstance(affected, list) or not affected or mirror.id not in affected or any(
                        not isinstance(mid, str) or session.get(MirrorRow, mid) is None
                        or session.get(MirrorRow, mid).source_id != source.id for mid in affected):
                        raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                    for mid in sorted(set(affected)):
                        self._gate(session, mid)
                gate = self._gate(session, mirror.id)
                expected = journal.get("replacement_epoch") or request["expected_history_epoch"]
                if gate.history_epoch != expected or evidence.get("history_epoch") != expected:
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                if evidence.get("validity") == "lost" and journal["state"] != "invalidated":
                    transitions = self.history.invalidate_history(session, mirror_ids=affected, reason="history_loss", operation_id=operation_id)
                    journal.update(state="invalidated", replacement_epoch=next(item["history_epoch"] for item in transitions if item["mirror_id"] == mirror.id),
                                   capture_generation=uuid4().hex, generation_id=uuid4().hex, next_attempt_at=None)
                    row.journal = journal
                    return journal["state"]
                if gate.status != "available":
                    raise MirrorError("MIRROR_HISTORY_INVALID", 409)
                if not mirror.enabled or any(evidence.get(key) is not True for key in ("ownership", "readiness", "resources")):
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                if not schema_resume_allowed(evidence.get("schema")):
                    journal.update(state="invalidated" if journal.get("replacement_epoch") else "blocked",
                                   fault_code="MIRROR_RECOVERY_AUTHORIZATION_REQUIRED")
                elif request["action"] == "reconcile_state":
                    self._classify(session, mirror.id, request)
                    # Classification authorizes intent only. No workflow replay adapter is bound here.
                    journal.update(state="blocked", fault_code="MIRROR_RECOVERY_AUTHORIZATION_REQUIRED")
                elif journal["state"] == "invalidated":
                    # Only committed invalidation may reach replacement dispatch.
                    busy = any(other.operation_id != operation_id and (other.journal["state"] == "dispatched" or other.journal.get("submission_uncertain") is True)
                               for other in session.scalars(select(RecoveryRow).where(RecoveryRow.source_id == source.id)))
                    window = SnapshotWindow.model_validate(source.snapshot_window) if source.snapshot_window else None
                    if busy:
                        journal["fault_code"] = "MIRROR_IN_USE"
                    elif request["action"] != "run_now" and not snapshot_dispatch_allowed(window, now):
                        journal["fault_code"] = "MIRROR_SNAPSHOT_WINDOW_CLOSED"
                    else:
                        journal["submission_uncertain"] = True
                        journal["submission_command"] = dict(operation_id=operation_id, kind="replacement", mirror_id=mirror.id,
                                            source_id=source.id, history_epoch=expected, empty=True, origin="recovery",
                                            capture_generation=journal["capture_generation"], generation_id=journal["generation_id"])
                        journal.update(state="submitting", fault_code=None)
                elif evidence.get("validity") == "retained" and gate.status == "available":
                    busy = any(other.operation_id != operation_id and (other.journal["state"] == "dispatched" or other.journal.get("submission_uncertain") is True)
                               for other in session.scalars(select(RecoveryRow).where(RecoveryRow.source_id == source.id)))
                    if busy:
                        journal["fault_code"] = "MIRROR_IN_USE"
                    else:
                        journal["submission_uncertain"] = True
                        journal["submission_command"] = journal.get("submission_command") or dict(
                            operation_id=operation_id, kind="resume", mirror_id=mirror.id, source_id=source.id,
                            history_epoch=expected, capture_generation=mirror.state.get("capture_generation"),
                            generation_id=mirror.state.get("published_generation_id"))
                        journal.update(state="submitting", fault_code=None)
                else:
                    self._defer(journal, "unknown", now)
            except MirrorError as exc:
                self._defer(journal, "unknown" if journal["state"] != "invalidated" else "invalidated", now, exc.code)
            row.journal = journal
            return journal["state"]


_recovery = None


def bind_recovery(service):
    global _recovery
    _recovery = service


def request_recovery(mirror_id, **kwargs):
    if _recovery is None:
        raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
    return _recovery.request_recovery(mirror_id, **kwargs)
