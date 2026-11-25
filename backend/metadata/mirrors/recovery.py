"""Durable, fail-closed recovery without a second target effects writer."""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
from random import SystemRandom
from uuid import uuid4

from psycopg.errors import RaiseException
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from backend.admin.audit import persist_audit_event
from backend.core.time import utc_now
from backend.metadata.capture.configuration import SnapshotWindow, snapshot_dispatch_allowed
from backend.metadata.capture.engines import CAPTURE_ENGINE_CODES
from backend.metadata.capture.store import load_binding
from backend.metadata.mirrors.history import admit_observed_history
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.store import SqlMirrorStore
from backend.metadata.mirrors.recovery_store import RecoveryRow, lock_source
from backend.metadata.mirrors.errors import MirrorError
from backend.metadata.mirrors.reconciliation import (
    publication_certificate_ref, record_replacement_publication, replacement_publication_allocation,
)
from backend.metadata.mirrors.types import Authority


__all__ = ["Recovery", "RuntimeDispatchAdapter", "bind_recovery", "request_recovery"]


@dataclass(frozen=True)
class _ReplacementIdentity:
    """The identity fields consumed by the committed target observer."""

    authority: Authority
    generation_id: str
    history_epoch: str


def schema_resume_allowed(evidence):
    if not isinstance(evidence, dict) or evidence.get("fingerprint_verified") is not True:
        return False
    if evidence.get("change") == "unchanged":
        return True
    return evidence.get("change") in {"add", "widen"} and all(
        evidence.get(key) is True for key in ("mapping_qualified", "detection_verified", "backfill_verified"))


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
                 retry_delays, audit=persist_audit_event, jitter=None, publication=None):
        if not retry_delays or any(type(delay) is not int or delay <= 0 for delay in retry_delays):
            raise ValueError("An approved bounded retry budget is required")
        self.session_factory = session_factory
        self.history = history
        self.runtime = runtime or RuntimeDispatchAdapter()
        self.clock = clock
        self.retry_delays = tuple(retry_delays)
        self.audit = audit
        self.publication = publication
        self.jitter = jitter or SystemRandom().uniform

    def _mirror(self, session, mirror_id):
        mirror = session.get(MirrorRow, mirror_id)
        if mirror is None:
            raise MirrorError("MIRROR_NOT_FOUND", 404)
        source = lock_source(session, mirror.source_id)
        session.refresh(mirror)
        if mirror.state.get("deletion_operation_id") or mirror.state.get("deletion_reservation"):
            raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
        return mirror, source

    def _gate(self, session, mirror_id):
        gate = session.scalar(select(HistoryGateRow).where(HistoryGateRow.mirror_id == mirror_id)
                              .with_for_update().execution_options(populate_existing=True))
        if gate is None:
            raise MirrorError("MIRROR_HISTORY_INVALID", 409)
        return gate

    def request_recovery(self, mirror_id, *, action, expected_history_epoch, actor_user_id,
                         actor_token_id=None, reason=None):
        if action not in {"retry", "run_now", "postpone", "manual"} or not actor_user_id:
            raise MirrorError("REQUEST_INVALID", 422)
        if reason is not None and (not isinstance(reason, str) or len(reason) > 1000):
            raise MirrorError("REQUEST_INVALID", 422)
        if action in {"run_now", "postpone", "manual"} and not (reason or "").strip():
            raise MirrorError("REQUEST_INVALID", 422)
        request = dict(action=action, expected_history_epoch=str(expected_history_epoch), reason=reason,
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
            operation_id = None
            active_rows = [row for row in rows if row.journal["state"] not in {"applied", "superseded"}]
            if active_rows:
                [active] = active_rows
                journal = active.journal
                state = journal["state"]
                if journal.get("submission_uncertain") or state == "dispatched":
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                replacement_epoch = journal.get("replacement_epoch")
                if replacement_epoch:
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

    def get_operation(self, operation_id):
        with self.session_factory() as session:
            row = session.get(RecoveryRow, operation_id)
            if row is None:
                raise MirrorError("MIRROR_NOT_FOUND", 404)
            return dict(operation_id=row.operation_id, **deepcopy(row.journal))

    def publish_replacement(self, *, operation_id, authority, certificate):
        with ExitStack() as target_guard, self.session_factory() as session, session.begin():
            row = session.get(RecoveryRow, operation_id)
            if row is None:
                raise MirrorError("MIRROR_NOT_FOUND", 404)
            mirror, source = self._mirror(session, row.mirror_id)
            session.refresh(row)
            journal = deepcopy(row.journal)
            applied = journal["state"] == "applied"
            if applied and "publication_receipt" not in journal:
                return journal["generation_id"]
            generation_id = journal.get("generation_id")
            epoch = journal.get("replacement_epoch")
            if (journal["state"] not in {"dispatched", "applied"} or not generation_id or not epoch
                    or not isinstance(authority, Authority) or authority.source_id != source.id
                    or authority.capture_generation != journal.get("capture_generation")):
                raise MirrorError("MIRROR_PUBLICATION_BLOCKED", 409)
            identity = dict(operation_id=operation_id, generation_id=generation_id)
            certificate_identity = dict(identity, table_identity=mirror.table_identity,
                                        capture_generation=authority.capture_generation)
            if not isinstance(certificate, dict) or any(
                certificate.get(key) != value for key, value in certificate_identity.items()
            ):
                raise MirrorError("MIRROR_PUBLICATION_BLOCKED", 409)
            try:
                certificate_ref = publication_certificate_ref(certificate)
            except (TypeError, ValueError):
                raise MirrorError("MIRROR_PUBLICATION_BLOCKED", 409) from None
            receipt = dict(authority=asdict(authority), generation_id=generation_id,
                           history_epoch=epoch, certificate_ref=certificate_ref)
            if applied:
                if journal["publication_receipt"] != receipt:
                    raise MirrorError("MIRROR_PUBLICATION_BLOCKED", 409)
                return generation_id
            if self.publication is None:
                raise MirrorError("MIRROR_PUBLICATION_BLOCKED", 409)
            self.history.require_fenced_loss(session, operation_id=operation_id, mirror_id=mirror.id,
                                             source_id=source.id, history_epoch=epoch)
            allocation = replacement_publication_allocation(session, mirror=mirror, **identity, authority=authority,
                                                            epoch=epoch, certificate_ref=certificate_ref)
            expected = _ReplacementIdentity(authority, generation_id, epoch)
            observation = dict(mirror_id=mirror.id, operation_id=operation_id, binding=expected, expected=expected)
            try:
                observed = target_guard.enter_context(self.publication.observe_committed(**observation))
            except DBAPIError as error:
                if not isinstance(error.orig, RaiseException) or error.orig.diag.message_primary != "MIRROR_PUBLICATION_BLOCKED":
                    raise
                observed = None
            if observed is None:
                if self.publication.publish_generation(**identity, authority=authority, certificate=certificate) != generation_id:
                    raise MirrorError("MIRROR_PUBLICATION_BLOCKED", 409)
                observed = target_guard.enter_context(self.publication.observe_committed(**observation))
            if (observed is None or observed.published_generation_id != generation_id
                    or publication_certificate_ref(observed.certificate["evidence"]) != certificate_ref):
                raise MirrorError("MIRROR_PUBLICATION_BLOCKED", 409)
            if allocation is not None:
                record_replacement_publication(session, allocation=allocation, observed=observed)
            gate = session.get(HistoryGateRow, mirror.id)
            lower, upper = admit_observed_history(session, mirror=mirror, gate=gate, history_epoch=epoch,
                                                  bound=observed.history_bound)
            SqlMirrorStore().save(session, dict(mirror.state, published_generation_id=generation_id,
                                capture_generation=authority.capture_generation, history_epoch=epoch,
                                retained_lower_bound=lower, committed_upper_bound=upper))
            journal.update(state="applied", submission_uncertain=False, publication_receipt=receipt)
            row.journal = journal
            return generation_id

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
                now = self.clock()
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
                now = self.clock()
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
                    binding = load_binding(session, source.id) if source.engine in CAPTURE_ENGINE_CODES else None
                    capture_generation = str(binding["capture_generation"] + 1) if binding else uuid4().hex
                    journal.update(state="invalidated", replacement_epoch=next(item["history_epoch"] for item in transitions if item["mirror_id"] == mirror.id),
                                   capture_generation=capture_generation, generation_id=uuid4().hex, next_attempt_at=None)
                    row.journal = journal
                    return journal["state"]
                if gate.status != "available":
                    raise MirrorError("MIRROR_HISTORY_INVALID", 409)
                if not mirror.enabled or any(evidence.get(key) is not True for key in ("ownership", "readiness", "resources")):
                    raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
                if not schema_resume_allowed(evidence.get("schema")):
                    journal.update(state="invalidated" if journal.get("replacement_epoch") else "blocked",
                                   fault_code="MIRROR_RECOVERY_AUTHORIZATION_REQUIRED")
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
