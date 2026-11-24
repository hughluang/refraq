"""Capture-runtime reconciliation of Mirror opens, generations, publication and stop evidence.

Each entry point verifies runtime-supplied evidence against the Management registry under
the Source and History locks, and commits the projection only when the evidence still holds.
"""

from contextlib import AbstractContextManager, ExitStack
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from hashlib import sha256
import json
import re
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.core.time import utc_now
from backend.metadata.capture.store import load_binding, load_operation
from backend.metadata.mirrors import journal, lifecycle
from backend.metadata.mirrors.errors import reject
from backend.metadata.mirrors.history import admit_observed_history
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.lifecycle import current_open
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.service import (
    add_operation, clear_stop_control, find_mirror, lock_mirror_source, new_operation_id, read_dispatch_scope, storage,
)
from backend.metadata.mirrors.store import SqlMirrorStore
from backend.metadata.mirrors.types import Authority, PartitionIdentity
from backend.metadata.models import SourceRow

__all__ = [
    "AppliedOpenPreparation",
    "CommittedOpenPublication",
    "ObserveCommittedOpenPublication",
    "OpenGenerationBinding",
    "OpenPublicationIdentity",
    "clear_mirror_stop_evidence",
    "confirm_retained_opens",
    "current_open_preparations",
    "initial_history_epoch",
    "lifecycle_checks",
    "publication_certificate_ref",
    "reconcile_open_generation",
    "reconcile_open_publication",
    "record_continuity_receipt",
    "record_mirror_stop_evidence",
    "record_replacement_publication",
    "replacement_publication_allocation",
    "request_reopen_baseline",
    "require_current_open_allocations",
    "require_current_retained_opens",
    "table_prerequisite_check",
    "validate_snapshot_completion",
]


@dataclass(frozen=True)
class OpenGenerationBinding:
    authority: Authority
    object_id: str
    table_identity: str
    qualified_table: str
    history_epoch: str
    schema_fingerprint: str
    columns: dict[str, str]
    key_columns: tuple[str, ...]
    partition_identity: PartitionIdentity
    start_offset: int


def initial_history_epoch(mirror_id):
    return uuid5(NAMESPACE_URL, f"refraq:mirror:initial-history:{mirror_id}").hex


def _replacement_open(session, state, entry):
    allocation = state.get("allocation", {})
    command = allocation.get("command", {})
    if command.get("kind") != "replace_owner":
        return None
    operation_id = command["operation_id"]
    replacement = command["replacement"]["scope"]
    submission = replacement["submission"]
    recovery = session.get(RecoveryRow, operation_id, populate_existing=True)
    epoch = submission["history_epoch"]
    if (recovery is None or recovery.source_id != state["source_id"] or recovery.mirror_id != entry["mirror_id"]
            or recovery.identity != replacement["recovery_request_identity"]
            or recovery.journal.get("state") not in {"dispatched", "applied"}
            or recovery.journal.get("submission_command") != submission
            or submission["capture_generation"] != str(state["capture_generation"])
            or epoch != _preparation_history_epoch(session, entry["mirror_id"], lock=True)):
        reject("MIRROR_CONTROL_CONFLICT")
    return submission, recovery.journal.get("request", {}).get("action")


def _included_scope(scope, selected_table_ids):
    included = [entry for entry in scope if entry["included"]]
    if selected_table_ids is None:
        return included
    identities = set(selected_table_ids)
    selected = [entry for entry in included if entry["table_identity"] in identities]
    if {entry["table_identity"] for entry in selected} != identities:
        reject("MIRROR_CONTROL_CONFLICT")
    return selected


def _superseded_scope_partition(operation, authority):
    claim = operation.get("allocation")
    if claim is None or operation.get("replacement_generation_id") is not None:
        return None
    previous = Authority(**claim["binding"]["authority"])
    if (previous.control_revision < authority.control_revision
            and replace(previous, control_revision=authority.control_revision) == authority):
        return claim["binding"]["partition_identity"]
    return None


def lifecycle_checks(source_id, scope):
    """Bind each check to an operator request before interacting with the observer."""
    store = storage()
    checks = {}
    with store.transaction() as session:
        store.lock_sources(session, {source_id})
        for entry in scope:
            if not entry["included"]:
                continue
            mirror = store.get(session, entry["mirror_id"])
            if not mirror or mirror["source_id"] != source_id or mirror["control"]["control_revision"] != entry["mirror_revision"]:
                continue
            request = journal.recheck_request(store.ops(session, mirror["id"]), mirror)
            if request:
                checks[mirror["id"]] = request["id"]
    return checks


def table_prerequisite_check(command, *, table, cause, passed, request_id=None):
    """Keep the table result only while its checked Source authority and revision remain current."""
    store = storage()
    with store.transaction() as session:
        source_id = command["source_id"]
        store.lock_sources(session, {source_id})
        state = load_binding(store.database(session), source_id) or {}
        if (any(command.get(key) != state.get(key) for key in (
                "binding_id", "control_revision", "credential_revision", "owner_epoch", "runtime_instance_id", "capture_generation"))
                or state.get("published_scope") != command["published_scope"]):
            return
        for entry in command["published_scope"]:
            if not entry["included"] or entry["qualified_table"] != table:
                continue
            mirror = store.get(session, entry["mirror_id"])
            if not mirror or not mirror["enabled"] or mirror["control"]["control_revision"] != entry["mirror_revision"]:
                continue
            ops = store.ops(session, mirror["id"])
            request = next((op for op in ops if op["id"] == request_id), None)
            if not request:
                continue
            blocker = mirror.get("blocker") or {}
            if passed and blocker.get("cause") != cause:
                continue
            at = utc_now().isoformat()
            pending_retry = request["kind"] == "retry" and request["state"] == "pending"
            if not passed and blocker.get("cause") == cause and not pending_retry:
                mirror["blocker"]["last_checked_at"] = at
                store.save(session, mirror)
                continue
            kind = cause + ("_verified" if passed else "_blocked")
            journal.note_check(store, session, mirror, request_id, kind, at=at, reference=at,
                               epoch=mirror.get("history_epoch"), generation=mirror["published_generation_id"])


def record_continuity_receipt(*, authority, scope, mirror_id, check_id, decision, published_operation_id=None):
    """Persist uncertain or superseded checks. A current conclusive check continues to its fenced transition."""
    store = storage()
    with store.transaction() as session:
        mirror = lock_mirror_source(session, mirror_id)
        state = load_binding(session, authority.source_id)
        entry = next((item for item in scope if item["mirror_id"] == mirror_id and item["included"]), None)
        if (not entry or not lifecycle.current_authority(state, authority, scope)
                or read_dispatch_scope(session, authority.source_id, state=state) != scope
                or mirror["control"]["control_revision"] != entry["mirror_revision"]):
            reject("MIRROR_CONTROL_CONFLICT")
        operations = store.ops(session, mirror_id)
        current = current_open(mirror, operations)
        if not current:
            return "recorded"
        request = next((op for op in operations if op["id"] == check_id), None)
        historical = (bool(current.get("reopen_baseline")) or current["state"] == "applied"
                      or (request or {}).get("result", {}).get("outcome") == "resolved_by_evidence")
        if not historical and decision["result"] != "unknown":
            return None
        allow_retained = (historical and current["state"] == "applied" and not current.get("reopen_baseline")
                          and published_operation_id is not None
                          and published_operation_id in {current["id"], current.get("retained_open_id")})
        kind = {"gap": "continuity_gap", "continuous": "continuity_verified", "unknown": "continuity_unknown"}[decision["result"]]
        if allow_retained and decision["result"] == "continuous" and check_id == current["id"]:
            # Steady-state delivery repeats retained-position validation on each poll.
            return "retained"
        journal.note_check(store, session, mirror, check_id, kind, at=decision["observed_at"],
                           reference=decision["evidence_ref"], epoch=mirror["history_epoch"],
                           generation=mirror["published_generation_id"], historical=historical)
        if allow_retained:
            return "retained"
        return "recorded"


def request_reopen_baseline(*, authority, published_scope, mirror_id, mirror_revision, operation_id, evidence_ref,
                            partition_identity, start_offset, history, check_id=None, observed_at=None):
    """Consume the deployment's authenticated, table-specific historical discontinuity decision."""
    store = storage()
    if not isinstance(store, SqlMirrorStore) or not isinstance(evidence_ref, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", evidence_ref):
        reject("MIRROR_CONTROL_CONFLICT")
    with store.transaction() as session:
        mirror = lock_mirror_source(session, mirror_id)
        state = load_binding(session, authority.source_id)
        scope = read_dispatch_scope(session, authority.source_id, state=state)
        if (scope != published_scope or not lifecycle.current_authority(state, authority, scope)
                or mirror["source_id"] != authority.source_id or not mirror["enabled"]
                or mirror["control"]["control_revision"] != mirror_revision):
            reject("MIRROR_CONTROL_CONFLICT")
        operations = store.ops(session, mirror_id)
        intent = [op for op in operations if op["kind"] == "open" and op["state"] == "pending"
                  and op["control_revision"] == mirror_revision and (op.get("operator_intent") or op.get("interrupted_partition")
                  or _superseded_scope_partition(op, authority))]
        published = [op for op in operations if op["kind"] == "open" and op["state"] == "applied"
                     and op.get("publication_receipt", {}).get("generation_id") == mirror["published_generation_id"]]
        if len(intent) != 1 or len(published) > 1 or operation_id not in {op["id"] for op in intent + published}:
            reject("MIRROR_CONTROL_CONFLICT")
        reopen, = intent
        previous = published[0] if published else None
        superseded = _superseded_scope_partition(reopen, authority)
        interrupted = superseded or reopen.get("interrupted_partition")
        if interrupted:
            fence = state.get("scope_fence", {})
            current_stamp = {k: state[k] for k in ("source_id", "binding_id", "owner_epoch", "runtime_instance_id",
                                                    "credential_revision", "control_revision", "capture_generation")}
            boundary = dict(mirror_revision=mirror_revision, evidence_ref=evidence_ref, start_offset=start_offset,
                            partition_identity=partition_identity)
            command = load_operation(session, fence["operation_id"]) if fence.get("operation_id") else None
            if (fence.get("authority") != current_stamp or not fence.get("mirror_receipts", {}).get(mirror_id)
                    or not command or command["command"]["published_scope"] != scope
                    or any(command["command"].get(key) != value for key, value in current_stamp.items())
                    or fence.get("table_boundaries", {}).get(mirror_id) != boundary or operation_id != reopen["id"]):
                reject("MIRROR_CONTROL_CONFLICT")
        elif previous is None:
            reject("MIRROR_CONTROL_CONFLICT")
        expected_partition = interrupted or previous["allocation"]["binding"]["partition_identity"]
        if (type(start_offset) is not int or start_offset < -1 or not isinstance(partition_identity, dict)
                or expected_partition != partition_identity):
            reject("MIRROR_CONTROL_CONFLICT")
        if superseded:
            store.save_op(session, dict(reopen, state="superseded"))
            reopen = add_operation(session, mirror, "open", new_operation_id(), interrupted_partition=interrupted)
        boundary = dict(start_offset=start_offset, partition_identity=partition_identity)
        invalidation_id = reopen["id"]
        gate = session.get(HistoryGateRow, mirror_id, with_for_update=True, populate_existing=True)
        if gate is None:
            if previous is not None or not interrupted:
                reject("MIRROR_CONTROL_CONFLICT")
            gate = HistoryGateRow(mirror_id=mirror_id, history_epoch=initial_history_epoch(mirror_id),
                                  lower_commit_seq=0, lower_entry_seq=0, status="available")
            session.add(gate)
            session.flush()
        if not reopen.get("reopen_baseline") and (
                gate.status != "available" or reopen.get("allocation") or
                (not interrupted and gate.history_epoch != previous["publication_receipt"]["history_epoch"])):
            reject("MIRROR_CONTROL_CONFLICT")
        transition, = history.invalidate_history(session, mirror_ids=[mirror_id], reason="table_gap", operation_id=invalidation_id,
                                                 table_boundary=boundary)
        baseline = dict(previous_generation_id=mirror["published_generation_id"], history_epoch=transition["history_epoch"],
                        invalidation_id=invalidation_id, evidence_ref=evidence_ref, **boundary)
        if reopen.get("reopen_baseline") not in (None, baseline):
            reject("MIRROR_CONTROL_CONFLICT")
        store.save_op(session, dict(reopen, reopen_baseline=baseline, observed_evidence_refs=[evidence_ref]))
        check = check_id or next((op["id"] for op in operations if op.get("operator_intent")
                                  and op["kind"] == "open" and op["control_revision"] == mirror_revision), None)
        journal.note_check(store, session, mirror, check, "continuity_gap", at=observed_at or utc_now().isoformat(),
                           reference=evidence_ref, epoch=transition["history_epoch"] if mirror["published_generation_id"] else None,
                           generation=mirror["published_generation_id"])
    history.consume_invalidation(operation_id=invalidation_id)


def _finish_reopen_invalidations(store, authority, history, selected_table_ids):
    source_id = authority.source_id
    with store.transaction() as session:
        state = load_binding(session, source_id) or {}
        includes = read_dispatch_scope(session, source_id, state=state)
        if selected_table_ids is not None:
            includes = [entry for entry in includes if entry["table_identity"] in selected_table_ids]
        pending, interrupted = [], []
        for entry in includes:
            for op in store.ops(session, entry["mirror_id"]):
                if (entry["included"] and op["kind"] == "open" and op["state"] == "pending"
                        and op["control_revision"] == entry["mirror_revision"]
                        and ((op.get("interrupted_partition") and not op.get("reopen_baseline"))
                             or _superseded_scope_partition(op, authority))):
                    boundary = state.get("scope_fence", {}).get("table_boundaries", {}).get(entry["mirror_id"])
                    if boundary:
                        interrupted.append(dict(boundary, mirror_id=entry["mirror_id"], operation_id=op["id"]))
            gate = session.get(HistoryGateRow, entry["mirror_id"])
            if gate is None or gate.status != "invalidating":
                continue
            for op in store.ops(session, entry["mirror_id"]):
                baseline = op.get("reopen_baseline")
                if baseline and baseline["history_epoch"] == gate.history_epoch:
                    pending.append(baseline["invalidation_id"])
    for operation_id in pending:
        history.consume_invalidation(operation_id=operation_id)
    for decision in interrupted:
        request_reopen_baseline(authority=authority, published_scope=state["published_scope"], history=history, **decision)


def _require_reopen_baseline(session, mirror, operation, epoch):
    baseline = operation.get("reopen_baseline")
    receipt = session.get(HistoryInvalidationRow, baseline["invalidation_id"]) if baseline else None
    if (not baseline or baseline["previous_generation_id"] != mirror["published_generation_id"]
            or baseline["history_epoch"] != epoch or receipt is None or receipt.reason != "table_gap"
            or receipt.status != "applied" or len(receipt.transitions) != 1
            or receipt.transitions[0]["mirror_id"] != mirror["id"] or receipt.transitions[0]["history_epoch"] != epoch):
        reject("MIRROR_CONTROL_CONFLICT")


def current_open_preparations(*, authority: Authority, published_scope, observe_committed, selected_table_ids=None, history=None):
    """Select current applied opens before preparing pending allocations for the Source."""
    store = storage()
    source_id = authority.source_id
    if history is not None and isinstance(store, SqlMirrorStore):
        _finish_reopen_invalidations(store, authority, history, selected_table_ids)
    with store.transaction() as session:
        store.lock_registry(session)
        store.lock_sources(session, {source_id})
        state = load_binding(store.database(session), source_id)
        scope = read_dispatch_scope(session, source_id, state=state)
        if not lifecycle.current_authority(state, authority, scope) or scope != published_scope:
            reject("MIRROR_CONTROL_CONFLICT")
        allocation = state.get("allocation", {})
        assignment_fence = allocation.get("evidence", {}).get("target_fence")
        assignment_receipts = {}
        if assignment_fence and all(state.get(key) == value for key, value in assignment_fence["authority"].items()):
            assignment_receipts = assignment_fence["mirror_receipts"]
        scope_fence = state.get("scope_fence")
        if scope_fence and all(state.get(key) == value for key, value in scope_fence["authority"].items()):
            fencing_command = load_operation(session, scope_fence["operation_id"])
            if (fencing_command and fencing_command["command"]["published_scope"] == published_scope
                    and fencing_command["command"]["control_revision"] == authority.control_revision):
                assignment_fence = scope_fence
                assignment_receipts = assignment_fence["mirror_receipts"]
        included = _included_scope(scope, selected_table_ids)
        pending, applied, preparations = [], [], []
        for entry in included:
            if scope_fence and entry["mirror_id"] in scope_fence.get("inconclusive_tables", {}):
                reject("MIRROR_CONTROL_CONFLICT")
            history = [op for op in store.ops(session, entry["mirror_id"]) if op["kind"] == "open"]
            if allocation.get("command", {}).get("kind") == "replace_owner":
                if len(included) != 1 or not isinstance(store, SqlMirrorStore):
                    reject("MIRROR_CONTROL_CONFLICT")
                submission, _ = _replacement_open(session, state, entry)
                operation_id = submission["operation_id"]
                operation = next((op for op in history if op["id"] == operation_id), None)
                if operation is None:
                    operation = add_operation(session, {"id": entry["mirror_id"], "control": {"control_revision": entry["mirror_revision"]}},
                                           "open", operation_id, replacement_generation_id=submission["generation_id"])
                if (operation.get("replacement_generation_id") != submission["generation_id"]
                        or operation["control_revision"] != entry["mirror_revision"]
                        or operation["state"] not in {"pending", "applied"}):
                    reject("MIRROR_CONTROL_CONFLICT")
                (applied if operation["state"] == "applied" else pending).append((entry, operation))
                continue
            published = [op for op in history if "publication_receipt" in op and op["state"] == "applied"]
            current = [op for op in history if op["state"] in {"pending", "applied"}
                       and op["control_revision"] == entry["mirror_revision"]]
            if len(current) != 1:
                reject("MIRROR_CONTROL_CONFLICT")
            operation, = current
            if operation.get("interrupted_partition") and not operation.get("reopen_baseline"):
                reject("MIRROR_CONTROL_CONFLICT")
            if published and not operation.get("reopen_baseline") and (operation["state"] == "pending" or operation.get("retained_open_id")):
                mirror = find_mirror(session, entry["mirror_id"])
                generation = mirror["published_generation_id"]
                retained = [op for op in published if generation
                            and op["publication_receipt"].get("generation_id") == generation]
                if len(retained) != 1 or operation.get("retained_open_id", retained[0]["id"]) != retained[0]["id"]:
                    reject("MIRROR_CONTROL_CONFLICT")
                applied.append((entry, retained[0]))
            else:
                (applied if operation["state"] == "applied" else pending).append((entry, operation))
        if applied:
            if not isinstance(store, SqlMirrorStore):
                reject("MIRROR_CONTROL_CONFLICT")
            stamp = dict(asdict(authority), capture_generation=state["capture_generation"])
            stamp["binding_id"] = stamp.pop("resource_binding_id")
            if (not assignment_fence or assignment_fence.get("authority") != stamp
                    or (assignment_fence != scope_fence and assignment_fence.get("operation_id") != allocation["command"]["operation_id"])):
                reject("MIRROR_CONTROL_CONFLICT")
            source = session.get(SourceRow, source_id, populate_existing=True)
            if (source is None or source.status != "active" or source.engine != "postgresql"
                    or not source.capture_credential_ciphertext
                    or source.capture_revision != authority.credential_revision):
                reject("MIRROR_CONTROL_CONFLICT")
            for entry, operation in applied:
                if not operation.get("publication_receipt", {}).get("authority"):
                    reject("MIRROR_CONTROL_CONFLICT")
                mirror_id = entry["mirror_id"]
                preparations.append(_observe_applied_open(session, store, state, entry, operation, authority,
                                                          assignment_receipts.get(mirror_id), observe_committed))
        selected = []
        for entry, operation in pending:
            mirror_id, revision = entry["mirror_id"], entry["mirror_revision"]
            claim = operation.get("allocation")
            if claim is not None and claim["binding"]["authority"] != asdict(authority):
                old = Authority(**claim["binding"]["authority"])
                if (old.source_id != source_id or old.resource_binding_id != authority.resource_binding_id
                        or old.owner_epoch >= authority.owner_epoch):
                    reject("MIRROR_CONTROL_CONFLICT")
                store.save_op(session, dict(operation, state="superseded"))
                operation_id = new_operation_id()
                add_operation(session, {"id": mirror_id, "control": {"control_revision": revision}}, "open", operation_id)
            else:
                operation_id = operation["id"]
            selected.append(dict(entry, operation_id=operation_id,
                                 history_epoch=_preparation_history_epoch(session, mirror_id),
                                 assignment_fence_receipt=assignment_receipts.get(mirror_id),
                                 **(dict(reopen_baseline=True, start_offset=operation["reopen_baseline"]["start_offset"],
                                         partition_identity=operation["reopen_baseline"]["partition_identity"])
                                    if operation.get("reopen_baseline") else {})))
        return selected, preparations


def _preparation_history_epoch(session, mirror_id, *, lock=False):
    gate = storage().history_gate(session, mirror_id, lock=lock)
    if gate is not None and gate.status == "invalidating":
        reject("MIRROR_CONTROL_CONFLICT")
    return gate.history_epoch if gate else initial_history_epoch(mirror_id)


def require_current_open_allocations(session, *, authority: Authority, allocations):
    """Validate observed allocations under the caller's Source lock without acquiring the registry."""
    store = storage()
    snapshot_mode = "window"
    for opened, generation_id in sorted(allocations, key=lambda item: item[0]["mirror_id"]):
        mirror_id = opened["mirror_id"]
        operation = next((op for op in store.ops(session, mirror_id) if op["id"] == opened["operation_id"]), None)
        claim = operation.get("allocation") if operation else None
        if (not claim or operation["kind"] != "open" or operation["state"] != "pending"
                or operation["control_revision"] != opened["mirror_revision"]
                or claim["observed"] is not True or claim["generation_id"] != generation_id
                or claim["binding"]["authority"] != asdict(authority)
                or claim["binding"]["history_epoch"] != opened["history_epoch"]
                or opened["history_epoch"] != _preparation_history_epoch(session, mirror_id, lock=True)):
            reject("MIRROR_CONTROL_CONFLICT")
        if opened.get("reopen_baseline") or operation.get("reopen_baseline"):
            if not opened.get("reopen_baseline"):
                reject("MIRROR_CONTROL_CONFLICT")
            _require_reopen_baseline(session, find_mirror(session, mirror_id), operation, opened["history_epoch"])
        if operation.get("replacement_generation_id") is not None:
            state = load_binding(session, authority.source_id)
            replacement = _replacement_open(session, state, opened)
            if replacement is None:
                reject("MIRROR_CONTROL_CONFLICT")
            submission, action = replacement
            if submission["operation_id"] != opened["operation_id"] or submission["generation_id"] != generation_id:
                reject("MIRROR_CONTROL_CONFLICT")
            if action == "run_now":
                if len(allocations) != 1:
                    reject("MIRROR_CONTROL_CONFLICT")
                snapshot_mode = "run_now"
    return snapshot_mode


def confirm_retained_opens(*, authority: Authority, published_scope, candidates, decisions=None, checks=None):
    """Accept a reopen only after the deployment confirms stream continuity under this authority."""
    store = storage()
    candidates = tuple(candidates)
    with store.transaction() as session:
        store.lock_registry(session)
        store.lock_sources(session, {authority.source_id})
        _check_retained_opens(session, authority, published_scope, candidates,
                              {item.binding.table_identity for item in candidates}, confirm=True,
                              decisions=decisions or {}, checks=checks or {})


def require_current_retained_opens(session, *, authority: Authority, published_scope, candidates, selected_table_ids=None):
    _check_retained_opens(session, authority, published_scope, candidates, selected_table_ids, confirm=False)


def _check_retained_opens(session, authority, published_scope, candidates, selected_table_ids, *, confirm, decisions=None, checks=None):
    """Recheck all applied opens under the caller's Source lock before live delivery."""
    store = storage()
    state = load_binding(session, authority.source_id)
    if (not lifecycle.current_authority(state, authority, published_scope)
            or state.get("applied_revision") != authority.control_revision
            or read_dispatch_scope(session, authority.source_id, state=state) != published_scope):
        reject("MIRROR_CONTROL_CONFLICT")
    entries = {entry["mirror_id"]: entry for entry in _included_scope(published_scope, selected_table_ids)}
    mirror_ids = {candidate.mirror_id for candidate in candidates}
    if not isinstance(store, SqlMirrorStore) or not candidates or len(mirror_ids) != len(candidates) or mirror_ids != entries.keys():
        reject("MIRROR_CONTROL_CONFLICT")
    for candidate in sorted(candidates, key=lambda item: item.mirror_id):
        mirror_id = candidate.mirror_id
        operations = store.ops(session, mirror_id)
        opened = next((operation for operation in operations if operation["id"] == candidate.operation_id), None)
        mirror = session.get(MirrorRow, mirror_id, with_for_update=True, populate_existing=True)
        gate = session.get(HistoryGateRow, mirror_id, with_for_update=True, populate_existing=True)
        if not opened or mirror is None or gate is None:
            reject("MIRROR_CONTROL_CONFLICT")
        epoch = candidate.binding.history_epoch
        receipt = opened.get("publication_receipt") or {}
        revision = entries[mirror_id]["mirror_revision"]
        current = [op for op in operations if op["kind"] == "open" and op["control_revision"] == revision
                   and op["state"] in {"applied", "pending"}]
        publisher = candidate.binding.authority
        if (len(current) != 1 or opened["kind"] != "open" or opened["state"] != "applied"
                or not _same_capture_stream(publisher, authority) or receipt.get("authority") != asdict(publisher)
                or receipt.get("generation_id") != candidate.generation_id
                or receipt.get("certificate_ref") != candidate.certificate_ref
                or receipt.get("history_epoch") != epoch or gate.history_epoch != epoch
                or gate.status != "available" or mirror.state["history_epoch"] != epoch
                or mirror.state["published_generation_id"] != candidate.generation_id):
            reject("MIRROR_CONTROL_CONFLICT")
        intent, = current
        if intent.get("reopen_baseline") and intent["id"] != opened["id"]:
            reject("MIRROR_CONTROL_CONFLICT")
        if intent["state"] == "pending":
            if not confirm or intent.get("allocation") or not intent.get("operator_intent"):
                reject("MIRROR_CONTROL_CONFLICT")
            decision = (decisions or {}).get(mirror_id, {})
            at = decision.get("observed_at") or utc_now().isoformat()
            check = (checks or {}).get(mirror_id, intent["id"])
            if (mirror.state.get("blocker") or {}).get("cause") in {"permission", "schema"}:
                reject("MIRROR_CONTROL_CONFLICT")
            journal.note_check(store, session, deepcopy(mirror.state), check, "continuity_verified",
                               at=at, reference=decision.get("evidence_ref") or candidate.certificate_ref,
                               epoch=epoch, generation=candidate.generation_id)
            intent = next(op for op in store.ops(session, mirror_id) if op["id"] == intent["id"])
            journal.result(intent, "continuity_verified", at, check if check != intent["id"] else None)
            store.save_op(session, dict(intent, state="applied", retained_open_id=opened["id"]))
        elif intent["id"] != opened["id"] and intent.get("retained_open_id") != opened["id"]:
            reject("MIRROR_CONTROL_CONFLICT")


def _same_capture_stream(publisher, current):
    return (publisher.source_id == current.source_id and publisher.resource_binding_id == current.resource_binding_id
            and publisher.capture_generation == current.capture_generation
            and publisher.owner_epoch <= current.owner_epoch and publisher.control_revision <= current.control_revision)


def _require_open_binding(session, store, mirror, binding):
    authority = binding.authority
    source_id = mirror["source_id"]
    identity = dict(source_id=authority.source_id, object_id=binding.object_id,
                    table_identity=binding.table_identity, qualified_table=binding.qualified_table)
    if any(mirror[key] != value for key, value in identity.items()):
        reject("MIRROR_CONTROL_CONFLICT")
    catalog = store.binding(session, binding.object_id)
    if catalog is None or any(catalog[key] != value for key, value in identity.items()):
        reject("MIRROR_CONTROL_CONFLICT")
    state = load_binding(store.database(session), source_id)
    scope = read_dispatch_scope(session, source_id, state=state)
    if (not lifecycle.current_authority(state, authority, scope)
            or not any(entry["mirror_id"] == mirror["id"] and entry["included"] for entry in scope)):
        reject("MIRROR_CONTROL_CONFLICT")
    return state


def _current_open_operation(session, store, mirror_id, operation_id, binding):
    mirror = lock_mirror_source(session, mirror_id)
    state = _require_open_binding(session, store, mirror, binding)
    gate = store.history_gate(session, mirror_id, lock=True)
    if gate is not None and gate.history_epoch != binding.history_epoch:
        reject("MIRROR_CONTROL_CONFLICT")
    revision = mirror["control"]["control_revision"]
    operation = next((op for op in store.ops(session, mirror_id) if op["id"] == operation_id), None)
    if (operation is None or operation["kind"] != "open" or operation["state"] != "pending"
            or operation["control_revision"] != revision):
        reject("MIRROR_CONTROL_CONFLICT")
    replacement = _replacement_open(session, state, {"mirror_id": mirror_id})
    if replacement is not None:
        submission, _ = replacement
        if (submission["operation_id"] != operation_id or submission["history_epoch"] != binding.history_epoch
                or submission["generation_id"] != operation.get("replacement_generation_id")):
            reject("MIRROR_CONTROL_CONFLICT")
    elif operation.get("replacement_generation_id") is not None:
        reject("MIRROR_CONTROL_CONFLICT")
    elif operation.get("reopen_baseline"):
        _require_reopen_baseline(session, mirror, operation, binding.history_epoch)
        baseline = operation["reopen_baseline"]
        if baseline["partition_identity"] != asdict(binding.partition_identity) or baseline["start_offset"] != binding.start_offset:
            reject("MIRROR_CONTROL_CONFLICT")
    return operation, revision


def reconcile_open_generation(*, mirror_id: str, operation_id: str, binding: OpenGenerationBinding,
                              verify_binding, allocate) -> str:
    """Reconcile the pending open through deployment-supplied verification and committed allocation.

    The verifier checks previously gathered fence, full schema/key and transport evidence against
    the request under management locks, and returns True on an exact match. The allocator accepts
    bootstrap arguments, requires the prepared target fence and returns the generation id after
    target commit. Allocation evidence is private to the pending operation.
    """
    binding = deepcopy(binding)
    if (not binding.history_epoch or not binding.schema_fingerprint or not binding.key_columns
            or len(set(binding.key_columns)) != len(binding.key_columns)
            or not set(binding.key_columns) <= binding.columns.keys()
            or not binding.partition_identity.runtime_cluster_id or not binding.partition_identity.topic_incarnation_id
            or binding.partition_identity.partition != 0 or binding.start_offset < -1):
        reject("MIRROR_CONTROL_CONFLICT")
    binding_data = asdict(binding)
    binding_data["columns"] = [list(item) for item in binding.columns.items()]
    binding_data["key_columns"] = list(binding.key_columns)

    store = storage()
    with store.transaction() as session:
        operation, revision = _current_open_operation(session, store, mirror_id, operation_id, binding)
        claim = operation.get("allocation")
        if claim is not None and (claim["binding"] != binding_data or claim["mirror_revision"] != revision):
            reject("MIRROR_CONTROL_CONFLICT")
        if verify_binding(binding=deepcopy(binding), mirror_id=mirror_id, operation_id=operation_id,
                          mirror_revision=revision) is not True:
            reject("MIRROR_CONTROL_CONFLICT")
        if claim is None:
            generation_id = operation.get("replacement_generation_id") or uuid4().hex
            claim = dict(generation_id=generation_id, mirror_revision=revision, binding=binding_data, observed=False)
            store.save_op(session, dict(operation, allocation=claim))
        generation_id = claim["generation_id"]
        if claim["observed"]:
            return generation_id

    if allocate(mirror_id=mirror_id, operation_id=operation_id, generation_id=generation_id,
                authority=binding.authority, table_identity=binding.table_identity, history_epoch=binding.history_epoch,
                schema_fingerprint=binding.schema_fingerprint, columns=dict(binding.columns),
                key_columns=binding.key_columns, partition_identity=binding.partition_identity,
                start_offset=binding.start_offset, require_prepared_fence=True) != generation_id:
        reject("MIRROR_CONTROL_CONFLICT")

    with store.transaction() as session:
        operation, revision = _current_open_operation(session, store, mirror_id, operation_id, binding)
        current = operation.get("allocation")
        if (revision != claim["mirror_revision"] or current is None
                or any(current[key] != claim[key] for key in ("generation_id", "mirror_revision", "binding"))):
            reject("MIRROR_CONTROL_CONFLICT")
        if not current["observed"]:
            store.save_op(session, dict(operation, allocation=dict(current, observed=True)))
    return generation_id


@dataclass(frozen=True)
class OpenPublicationIdentity:
    authority: Authority
    generation_id: str
    history_epoch: str
    snapshot_operation_id: str
    scan_offset: int
    completion_offset: int
    certificate_ref: str


@dataclass(frozen=True)
class CommittedOpenPublication:
    published_generation_id: str
    allocation: dict
    certificate: dict
    applied_offset: int
    history_bound: dict


@dataclass(frozen=True)
class AppliedOpenPreparation:
    mirror_id: str
    operation_id: str
    binding: OpenGenerationBinding
    identity: OpenPublicationIdentity
    observed: CommittedOpenPublication


class ObserveCommittedOpenPublication(Protocol):
    def __call__(
        self, *, mirror_id: str, operation_id: str, binding: OpenGenerationBinding,
        expected: OpenPublicationIdentity,
    ) -> AbstractContextManager[CommittedOpenPublication | None]:
        """Authenticate and guard a current target view through Management commit or rollback.

        Return the committed pointer, delivery_metadata for that generation, the complete
        certificates row, the generation's applied offset and history_bound. The bounded
        guard must prevent changes to this view and must never acquire Management locks.
        """
        ...


def publication_certificate_ref(evidence: dict) -> str:
    """Reference the exact certificate evidence independently of target cursor movement."""
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + sha256(payload.encode()).hexdigest()


def _open_publication_binding(operation, expected):
    claim = operation.get("allocation")
    if (not claim or claim["observed"] is not True or claim["generation_id"] != expected.generation_id
            or claim["mirror_revision"] != operation["control_revision"]
            or claim["binding"]["authority"] != asdict(expected.authority)
            or claim["binding"]["history_epoch"] != expected.history_epoch):
        reject("MIRROR_CONTROL_CONFLICT")
    data = claim["binding"]
    return OpenGenerationBinding(**dict(data, authority=expected.authority, columns=dict(data["columns"]),
                                        key_columns=tuple(data["key_columns"]),
                                        partition_identity=PartitionIdentity(**data["partition_identity"])))


def _publication_snapshot(state, mirror_id, operation, binding, expected):
    snapshot = state.get("incremental_snapshots", {}).get("generations", {}).get(expected.generation_id)
    allocated = dict(authority=asdict(binding.authority), mirror_id=mirror_id,
                     mirror_revision=operation["control_revision"], allocation_operation_id=operation["id"],
                     generation_id=expected.generation_id, table_identity=binding.table_identity,
                     qualified_table=binding.qualified_table, history_epoch=binding.history_epoch,
                     schema_fingerprint=binding.schema_fingerprint, data_partition=asdict(binding.partition_identity))
    if (not snapshot or snapshot.get("state") != "catching_up" or snapshot.get("receipt") is not True
            or snapshot.get("id") != expected.snapshot_operation_id
            or snapshot.get("scan", {}).get("offset") != expected.scan_offset
            or snapshot.get("completion", {}).get("offset") != expected.completion_offset
            or any(snapshot.get("binding", {}).get(key) != value for key, value in allocated.items())):
        reject("MIRROR_CONTROL_CONFLICT")
    return snapshot["binding"]


def _validate_observed_publication(observed, *, mirror_id, operation_id, binding, expected, snapshot, current_authority=None):
    if not isinstance(observed, CommittedOpenPublication) or observed.published_generation_id != expected.generation_id:
        reject("MIRROR_CONTROL_CONFLICT")
    allocation = observed.allocation
    certificate = observed.certificate
    shared = dict(operation_id=operation_id, generation_id=expected.generation_id,
                  table_identity=binding.table_identity, capture_generation=binding.authority.capture_generation,
                  schema_fingerprint=binding.schema_fingerprint, partition_identity=asdict(binding.partition_identity))
    aliases = {"timestamp": "timestamp without time zone", "timestamptz": "timestamp with time zone"}
    target_binding = dict(shared, authority=asdict(current_authority or binding.authority), mirror_id=mirror_id,
                          history_epoch=binding.history_epoch, start_offset=binding.start_offset,
                          column_names=list(binding.columns), key_columns=list(binding.key_columns),
                          native_types={name: aliases.get(kind, kind) for name, kind in binding.columns.items()},
                          status="published", cleanup_pending=False)
    if (not isinstance(allocation, dict) or any(allocation.get(key) != value for key, value in target_binding.items())
            or not isinstance(certificate, dict) or certificate.get("published") is not True
            or not isinstance(certificate.get("verified_by"), str) or not certificate["verified_by"]
            or certificate.get("authority") != asdict(expected.authority)
            or certificate.get("operation_id") != operation_id or certificate.get("generation_id") != expected.generation_id):
        reject("MIRROR_CONTROL_CONFLICT")
    evidence = certificate.get("evidence")
    if (not isinstance(evidence, dict) or any(evidence.get(key) != value for key, value in shared.items())
            or publication_certificate_ref(evidence) != expected.certificate_ref
            or type(evidence.get("end_offset")) is not int or type(observed.applied_offset) is not int
            or not binding.start_offset <= evidence["end_offset"] <= observed.applied_offset):
        reject("MIRROR_CONTROL_CONFLICT")
    validate_snapshot_completion(evidence, qualified_table=binding.qualified_table, expected=expected, snapshot=snapshot)


def validate_snapshot_completion(evidence, *, qualified_table, expected, snapshot):
    completion = evidence.get("source_completion")
    if (not isinstance(completion, dict) or completion.get("operation") != expected.snapshot_operation_id
            or completion.get("table") != qualified_table
            or any(completion.get(key) != snapshot[key] for key in ("notification_topic", "notification_partition"))):
        reject("MIRROR_CONTROL_CONFLICT")
    terminals = completion.get("terminals")
    required = (("TABLE_SCAN_COMPLETED", expected.scan_offset), ("COMPLETED", expected.completion_offset))
    if (not isinstance(terminals, list) or len(terminals) != len(required)
            or any(not isinstance(terminal, dict) or type(terminal.get("offset")) is not int
                   or terminal["offset"] != offset or not isinstance(terminal.get("event"), dict)
                   or terminal["event"].get("id") != expected.snapshot_operation_id
                   or terminal["event"].get("type") != kind
                   for terminal, (kind, offset) in zip(terminals, required))):
        reject("MIRROR_CONTROL_CONFLICT")


def _observe_applied_open(session, store, state, entry, operation, authority, fence_receipt, observe_committed):
    mirror_id = entry["mirror_id"]
    receipt = operation.get("publication_receipt")
    replacement = _replacement_open(session, state, entry)
    epoch = _preparation_history_epoch(session, mirror_id, lock=True)
    if (replacement is not None and replacement[0]["history_epoch"] != epoch
            or not isinstance(receipt, dict) or not isinstance(receipt.get("authority"), dict)
            or receipt.get("history_epoch") != epoch or not isinstance(fence_receipt, str) or not fence_receipt):
        reject("MIRROR_CONTROL_CONFLICT")
    publisher = Authority(**receipt["authority"])
    if not _same_capture_stream(publisher, authority):
        reject("MIRROR_CONTROL_CONFLICT")
    expected = OpenPublicationIdentity(**dict(receipt, authority=publisher))
    if (not expected.generation_id or not expected.snapshot_operation_id or not expected.certificate_ref
            or type(expected.scan_offset) is not int or type(expected.completion_offset) is not int
            or not 0 <= expected.scan_offset < expected.completion_offset):
        reject("MIRROR_CONTROL_CONFLICT")
    binding = _open_publication_binding(operation, expected)
    mirror_row = session.get(MirrorRow, mirror_id, with_for_update=True, populate_existing=True)
    if mirror_row is None:
        reject("MIRROR_CONTROL_CONFLICT")
    mirror = mirror_row.state
    if (mirror["published_generation_id"] != expected.generation_id
            or mirror.get("capture_generation") != authority.capture_generation
            or mirror.get("history_epoch") != expected.history_epoch):
        reject("MIRROR_CONTROL_CONFLICT")
    _require_open_binding(session, store, mirror, replace(binding, authority=authority))
    snapshot = _publication_snapshot(state, mirror_id, operation, binding, expected)
    gate = session.get(HistoryGateRow, mirror_id, with_for_update=True, populate_existing=True)
    if gate is None or gate.status != "available" or gate.history_epoch != expected.history_epoch:
        reject("MIRROR_CONTROL_CONFLICT")
    operation_id = operation["id"]
    fence = dict(current_authority=authority, fence_receipt=fence_receipt) if authority != publisher else {}
    with observe_committed(mirror_id=mirror_id, operation_id=operation_id, binding=binding, expected=expected, **fence) as observed:
        _validate_observed_publication(observed, mirror_id=mirror_id, operation_id=operation_id,
                                       binding=binding, expected=expected, snapshot=snapshot, current_authority=authority)
        bound = observed.history_bound
        if (observed.allocation.get("fence_receipt") != fence_receipt or not isinstance(bound, dict)
                or bound.get("mirror_id") != mirror_id or bound.get("source_id") != authority.source_id
                or bound.get("history_epoch") != expected.history_epoch):
            reject("MIRROR_CONTROL_CONFLICT")
        return AppliedOpenPreparation(mirror_id, operation_id, binding, expected, observed)


def replacement_publication_allocation(session, *, mirror, operation_id, authority, generation_id, epoch, certificate_ref):
    state = load_binding(session, mirror.source_id)
    if state is None:
        return None
    store = storage()
    scope = read_dispatch_scope(session, mirror.source_id, state=state)
    if (not lifecycle.current_authority(state, authority, scope)
            or state.get("applied_revision") != authority.control_revision):
        reject("MIRROR_PUBLICATION_BLOCKED")
    replacement = _replacement_open(session, state, {"mirror_id": mirror.id})
    operation = next((op for op in store.ops(session, mirror.id) if op["id"] == operation_id), None)
    if (replacement is None or replacement[0]["operation_id"] != operation_id
            or replacement[0]["generation_id"] != generation_id or replacement[0]["history_epoch"] != epoch
            or operation is None or operation["state"] != "pending" or operation["kind"] != "open"
            or operation["control_revision"] != mirror.state["control"]["control_revision"]):
        reject("MIRROR_PUBLICATION_BLOCKED")
    snapshot = state.get("incremental_snapshots", {}).get("generations", {}).get(generation_id) or {}
    expected = OpenPublicationIdentity(authority, generation_id, epoch, snapshot.get("id"),
                                       snapshot.get("scan", {}).get("offset"),
                                       snapshot.get("completion", {}).get("offset"), certificate_ref)
    if (not expected.snapshot_operation_id or type(expected.scan_offset) is not int
            or type(expected.completion_offset) is not int or not 0 <= expected.scan_offset < expected.completion_offset):
        reject("MIRROR_PUBLICATION_BLOCKED")
    binding = _open_publication_binding(operation, expected)
    _require_open_binding(session, store, mirror.state, binding)
    snapshot_binding = _publication_snapshot(state, mirror.id, operation, binding, expected)
    return operation, binding, expected, snapshot_binding


def record_replacement_publication(session, *, allocation, observed):
    operation, binding, expected, snapshot = allocation
    _validate_observed_publication(observed, mirror_id=operation["mirror_id"], operation_id=operation["id"],
                                   binding=binding, expected=expected, snapshot=snapshot)
    _record_publication(session, operation, asdict(expected))


def _record_publication(session, operation, receipt):
    at = utc_now().isoformat()
    journal.observation(operation, "published", at=at, reference=receipt["certificate_ref"],
                        epoch=receipt["history_epoch"], generation=receipt["generation_id"])
    journal.result(operation, "published", at)
    storage().save_op(session, dict(operation, state="applied", publication_receipt=receipt))


def reconcile_open_publication(
    *, mirror_id: str, operation_id: str, expected: OpenPublicationIdentity,
    observe_committed: ObserveCommittedOpenPublication,
) -> Literal["applied", "already_applied"]:
    """Project the first published generation or acknowledge its historical receipt."""
    store = storage()
    if (not isinstance(store, SqlMirrorStore) or not isinstance(expected, OpenPublicationIdentity)
            or not isinstance(expected.authority, Authority)
            or not expected.snapshot_operation_id or not expected.certificate_ref
            or type(expected.scan_offset) is not int or type(expected.completion_offset) is not int
            or not 0 <= expected.scan_offset < expected.completion_offset):
        reject("MIRROR_CONTROL_CONFLICT")
    receipt = asdict(expected)
    authority = receipt["authority"]
    if any(type(authority[key]) is not int for key in ("owner_epoch", "control_revision", "credential_revision")):
        reject("MIRROR_CONTROL_CONFLICT")
    with ExitStack() as target_guard, store.transaction() as session:
        mirror = lock_mirror_source(session, mirror_id)
        operation = next((op for op in store.ops(session, mirror_id) if op["id"] == operation_id), None)
        if operation is None or operation["kind"] != "open":
            reject("MIRROR_CONTROL_CONFLICT")
        if "publication_receipt" in operation:
            if operation["state"] != "applied" or operation["publication_receipt"] != receipt:
                reject("MIRROR_CONTROL_CONFLICT")
            return "already_applied"
        if operation["state"] != "pending" or operation["control_revision"] != mirror["control"]["control_revision"]:
            reject("MIRROR_CONTROL_CONFLICT")
        if operation.get("reopen_baseline") or mirror["published_generation_id"] is not None:
            _require_reopen_baseline(session, mirror, operation, expected.history_epoch)
            if expected.generation_id == mirror["published_generation_id"]:
                reject("MIRROR_CONTROL_CONFLICT")
        elif expected.history_epoch != initial_history_epoch(mirror_id):
            reject("MIRROR_CONTROL_CONFLICT")
        binding = _open_publication_binding(operation, expected)
        state = _require_open_binding(session, store, mirror, binding)
        source = session.get(SourceRow, mirror["source_id"], populate_existing=True)
        if (source.status != "active" or source.engine != "postgresql" or not source.capture_credential_ciphertext
                or source.capture_revision != expected.authority.credential_revision
                or state.get("applied_revision") != expected.authority.control_revision):
            reject("MIRROR_CONTROL_CONFLICT")
        snapshot = _publication_snapshot(state, mirror_id, operation, binding, expected)
        mirror_row = session.get(MirrorRow, mirror_id, with_for_update=True)
        gate = session.get(HistoryGateRow, mirror_id, with_for_update=True, populate_existing=True)
        if gate is not None and (gate.status != "available" or gate.history_epoch != expected.history_epoch):
            reject("MIRROR_CONTROL_CONFLICT")
        observed = target_guard.enter_context(observe_committed(
            mirror_id=mirror_id, operation_id=operation_id, binding=deepcopy(binding), expected=expected,
        ))
        _validate_observed_publication(observed, mirror_id=mirror_id, operation_id=operation_id,
                                       binding=binding, expected=expected, snapshot=snapshot)
        bound = observed.history_bound
        if not isinstance(bound, dict) or bound.get("mirror_id") != mirror_id:
            reject("MIRROR_CONTROL_CONFLICT")
        lower, upper = admit_observed_history(session, mirror=mirror_row, gate=gate,
                                              history_epoch=expected.history_epoch, bound=bound)
        store.save(session, dict(mirror, status="ready", published_generation_id=observed.published_generation_id,
                                 capture_generation=binding.authority.capture_generation,
                                 history_epoch=bound["history_epoch"], retained_lower_bound=lower,
                                 committed_upper_bound=upper))
        _record_publication(session, operation, receipt)
        return "applied"


def record_mirror_stop_evidence(session, command, evidence, *, exclusions=None):
    """Project a full Source stop or individually proven exclusions onto their Mirror revisions."""
    store = storage()
    if session is None:
        with store.transaction() as memory_session:
            record_mirror_stop_evidence(memory_session, command, evidence, exclusions=exclusions)
        return
    for entry in command["published_scope"]:
        if entry["included"] or (exclusions is not None and entry["mirror_id"] not in exclusions):
            continue
        mirror = store.get(session, entry["mirror_id"])
        if (mirror is None or mirror["enabled"] or mirror["status"] != "disable_pending"
                or mirror["source_id"] != command["source_id"]
                or mirror["control"]["control_revision"] != entry["mirror_revision"]
                or any(mirror[key] != entry[key] for key in ("table_identity", "qualified_table"))):
            continue
        for operation in store.ops(session, mirror["id"]):
            if (operation["kind"] != "disable" or operation["state"] != "pending"
                    or operation["control_revision"] != entry["mirror_revision"]
                    or datetime.fromisoformat(operation["requested_at"]) > datetime.fromisoformat(command["requested_at"])):
                continue
            mirror["control"].update(
                credential_revision=command["credential_revision"],
                owner_epoch=command["owner_epoch"],
                runtime_instance_id=command["runtime_instance_id"],
                applied_revision=entry["mirror_revision"],
                observed_at=evidence["observed_at"],
                stop_ack=dict(operation_id=operation["id"], source_operation_id=command["operation_id"],
                              observed_at=evidence["observed_at"]),
            )
            mirror["status"] = "disabled"
            store.save(session, mirror)
            refs = [command["operation_id"]]
            if exclusions is not None:
                refs.extend(exclusions[entry["mirror_id"]])
            operation.update(state="applied", observed_evidence_refs=refs)
            journal.project_stop_receipt(mirror, operation)
            store.save_op(session, operation)


def clear_mirror_stop_evidence(session, published_scope, source_operation_id):
    """Retire projections when the acknowledged Source authority is superseded."""
    store = storage()
    if session is None:
        with store.transaction() as memory_session:
            clear_mirror_stop_evidence(memory_session, published_scope, source_operation_id)
        return
    for entry in published_scope:
        mirror = store.get(session, entry["mirror_id"])
        if mirror is None:
            continue
        acknowledgment = mirror["control"].get("stop_ack")
        if acknowledgment is None or acknowledgment["source_operation_id"] != source_operation_id:
            continue
        for operation in store.ops(session, mirror["id"]):
            if operation["id"] == acknowledgment["operation_id"]:
                journal.project_stop_receipt(mirror, operation)
                journal.observation(operation, "stop_retired", at=utc_now().isoformat(), reference=source_operation_id,
                                    epoch=mirror.get("history_epoch"), generation=mirror["published_generation_id"])
                operation.pop("result", None)
                store.save_op(session, dict(operation, state="pending", observed_evidence_refs=[]))
        clear_stop_control(mirror["control"])
        mirror["status"] = "disable_pending"
        store.save(session, mirror)
