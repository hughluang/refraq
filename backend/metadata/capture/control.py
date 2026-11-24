"""Durable Source capture intent; no external provisioning occurs in this module."""

from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256
import json
import re
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now
from backend.metadata.capture.store import (
    list_operations,
    load_binding,
    load_operation,
    promote_replacement_binding,
    save_binding,
    save_operation,
)
from backend.metadata.errors import SourceCaptureControlConflict, SourceNotFound
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.reconciliation import clear_mirror_stop_evidence, record_mirror_stop_evidence
from backend.metadata.mirrors.service import read_dispatch_scope, read_published_scope
from backend.metadata.sources.store import SourceRecord, get_source_store


AUTHORITY_KEYS = (
    "source_id",
    "binding_id",
    "owner_epoch",
    "runtime_instance_id",
    "capture_generation",
    "control_revision",
    "credential_revision",
)


def included_tables(published_scope):
    return [table for table in published_scope if table["included"]]


def selected_tables(profile_scope, published_scope):
    qualified = set(profile_scope.get("tables", []))
    return [entry for entry in included_tables(published_scope) if entry["qualified_table"] in qualified]


def profile_matches_scope(profile_scope, published_scope):
    return bool(selected_tables(profile_scope, published_scope))


def table_exclusion_refs(scope, exclusions):
    """Check exact excluded registry revisions and independently observed receipt digests."""
    excluded = {row["mirror_id"]: row for row in scope if not row["included"]}
    proof_keys = ("connector_excluded_ref", "inflight_drained_ref", "target_fence_ref")
    refs = {}
    if not isinstance(exclusions, list):
        raise SourceCaptureControlConflict()
    for item in exclusions:
        if not isinstance(item, dict) or set(item) != {"scope_entry", *proof_keys}:
            raise SourceCaptureControlConflict()
        entry = item["scope_entry"]
        if not isinstance(entry, dict) or not isinstance(entry.get("mirror_id"), str):
            raise SourceCaptureControlConflict()
        mirror_id = entry["mirror_id"]
        if (entry != excluded.get(mirror_id) or entry["included"] is not False
                or type(entry["mirror_revision"]) is not int or mirror_id in refs
                or any(not isinstance(item[key], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", item[key])
                       for key in proof_keys)):
            raise SourceCaptureControlConflict()
        refs[mirror_id] = [item[key] for key in proof_keys]
    return refs


def _desired(source, published_scope, allocation_scope):
    profile = allocation_scope.get("profile")
    wanted = selected_tables(profile, published_scope) if profile else included_tables(published_scope)
    if source.status == "active" and source.capture_credential_ciphertext and wanted:
        return "configured"
    return "stopped"


@contextmanager
def source_control_transaction(source_id: str):
    store = get_source_store()
    if get_settings().store_backend == "persistent":
        with session_scope() as session:
            source = store.get_source_for_update(session, source_id)
            if source is None:
                raise SourceNotFound()
            yield session, source
    else:
        with store.capture_lock:
            source = store.get_source(source_id)
            if source is None:
                raise SourceNotFound()
            yield None, source


def _new_binding(source_id):
    return dict(source_id=source_id, binding_id=f"cap_{uuid4().hex}", capture_generation=1,
                owner_epoch=0, runtime_instance_id=None, control_revision=0, published_scope=[])


def _command(state, source, operation_id):
    command = {key: state[key] for key in AUTHORITY_KEYS}
    return dict(command, operation_id=operation_id,
                kind="stop" if state["desired"] == "stopped" else "reconcile",
                snapshot_window=source.snapshot_window, requested_at=utc_now().isoformat(),
                published_scope=state.get("published_scope", []))


def _advance_intent(session, state, source, published_scope):
    _retire_stop_evidence(session, state)
    state.update(control_revision=state["control_revision"] + 1,
                 credential_revision=source.capture_revision, stop_ack=None,
                 applied_revision=None, observed_at=None, published_scope=published_scope,
                 desired=_desired(source, published_scope, state.get("allocation", {}).get("scope", {})))
    command = _command(state, source, f"cop_{uuid4().hex}")
    save_binding(session, state)
    save_operation(session, command)
    return command


def _retire_stop_evidence(session, state):
    scope = state.get("published_scope")
    if scope and state.get("stop_ack") is not None:
        clear_mirror_stop_evidence(session, scope, state["stop_ack"]["operation_id"])
    partial = state.pop("table_stops", None)
    if partial is not None:
        clear_mirror_stop_evidence(session, scope, partial["operation_id"])


def reconcile_published_scope(source_id):
    """Commit the current scope and corresponding command before runtime dispatch."""
    with source_control_transaction(source_id) as (session, source):
        state = load_binding(session, source_id)
        if state is None:
            return
        pending = state.get("pending_allocation")
        if pending and pending["previous_authority"] == {key: state[key] for key in AUTHORITY_KEYS}:
            # The gateway may have fenced the predecessor before losing its reply.
            # Resolve that exact reservation before issuing a new scope command.
            return
        scope = read_dispatch_scope(session, source_id, state=state)
        if (scope == state.get("published_scope", [])
                and state["desired"] == _desired(source, scope, state.get("allocation", {}).get("scope", {}))):
            return
        _advance_intent(session, state, source, scope)


def record_source_intent(
    session: Session | None,
    before: SourceRecord | None,
    after: SourceRecord,
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> None:
    state = load_binding(session, after.id)
    if state is None and not (
        after.capture_credential_ciphertext
        or (before is not None and before.capture_credential_ciphertext)
    ):
        return
    if state is None:
        state = _new_binding(after.id)
    elif before is not None and (
        before.status == after.status
        and before.capture_revision == after.capture_revision
        and before.snapshot_window == after.snapshot_window
    ):
        return
    command = _advance_intent(session, state, after, state.get("published_scope", []))
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="source",
        resource_id=after.id,
        action="source.capture_intent",
        result="success",
        detail={
            key: command[key]
            for key in (
                "operation_id",
                "binding_id",
                "kind",
                "control_revision",
                "credential_revision",
            )
        },
        session=session,
    )


def _allocation_context(session, source, state, profile_scope, *, ordinary_takeover):
    if state is None or state["credential_revision"] != source.capture_revision:
        raise SourceCaptureControlConflict()
    current = state.get("published_scope", [])
    previous = {key: state[key] for key in AUTHORITY_KEYS}
    desired = _desired(source, current, state.get("allocation", {}).get("scope", {}))
    if state["desired"] != desired:
        raise SourceCaptureControlConflict()
    pending = state.get("pending_allocation") if ordinary_takeover else None
    if pending and pending["previous_authority"] == previous:
        if pending["scope"]["profile"] != profile_scope:
            raise SourceCaptureControlConflict()
        return previous, pending["scope"]
    published_scope = read_published_scope(session, source.id)
    if current != published_scope and not (
        ordinary_takeover and current == read_dispatch_scope(session, source.id, state=state)
    ):
        raise SourceCaptureControlConflict()
    if desired == "configured" and not profile_matches_scope(profile_scope, published_scope):
        raise SourceCaptureControlConflict()
    return previous, {"profile": profile_scope, "published_scope": published_scope}


def allocate_owner(*, source_id, operation_id, signed_proof, signals):
    """Reserve exact intent, then promote only after the gateway confirms the fence."""
    if (not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", operation_id)
            or not isinstance(signed_proof, str) or not signed_proof or signals.verifier is None):
        raise SourceCaptureControlConflict()
    request_digest = sha256(signed_proof.encode()).hexdigest()
    with source_control_transaction(source_id) as (session, source):
        state = load_binding(session, source_id)
        existing = load_operation(session, operation_id)
        if existing is not None:
            command = existing["command"]
            committed = state.get("allocation", {}) if state else {}
            if (command["kind"] == "replace_owner" or committed.get("command") != command
                    or committed["scope"]["profile"] != signals.scope
                    or committed.get("request_digest") != request_digest
                    or command["runtime_instance_id"] != signals.runtime_instance_id):
                raise SourceCaptureControlConflict()
            return command
        previous, scope = _allocation_context(session, source, state, signals.scope, ordinary_takeover=True)
        if replacement_blocks_lifecycle(session, state):
            raise SourceCaptureControlConflict()
        authority = {**previous, "owner_epoch": state["owner_epoch"] + 1,
                     "runtime_instance_id": signals.runtime_instance_id,
                     "control_revision": state["control_revision"] + 1}
        pending = state.get("pending_allocation")
        if pending is not None and pending["previous_authority"] == previous:
            command = pending["command"]
            if (command["operation_id"] != operation_id or pending["request_digest"] != request_digest
                    or any(command[key] != authority[key] for key in AUTHORITY_KEYS)):
                raise SourceCaptureControlConflict()
        else:
            if pending is not None and pending["command"]["operation_id"] == operation_id:
                raise SourceCaptureControlConflict()
            claims = signals.verifier.verify(signed_proof, purpose="owner_allocation", authority=authority,
                                             scope=scope, operation_id=operation_id)
            if claims.get("previous_authority") != previous:
                raise SourceCaptureControlConflict()
            desired = _desired(source, scope["published_scope"], scope)
            command = _command(dict(authority, desired=desired, published_scope=scope["published_scope"]), source, operation_id)
            pending = dict(command=command, scope=scope, previous_authority=previous,
                           request_digest=request_digest)
            state["pending_allocation"] = pending
            save_binding(session, state)

    with source_control_transaction(source_id) as (session, source):
        state = load_binding(session, source_id)
        if (state.get("allocation", {}).get("command") == command
                and state["allocation"]["request_digest"] == request_digest):
            return command
        current, scope = _allocation_context(session, source, state, signals.scope, ordinary_takeover=True)
        if (state.get("pending_allocation") != pending or current != previous
                or load_operation(session, operation_id) is not None):
            raise SourceCaptureControlConflict()
        evidence = signals.allocation_observation(pending, signed_proof)
        persist_audit_event(
            actor_user_id=None, actor_token_id=None, resource_type="source", resource_id=source_id,
            action="source.capture_owner_allocated", result="success", session=session,
            detail={key: command[key] for key in ("operation_id", "binding_id", "owner_epoch", "control_revision")},
        )
        save_operation(session, command)
        state.pop("pending_allocation")
        _retire_stop_evidence(session, state)
        ledger = state.get("incremental_snapshots", {})
        active = ledger.get("active")
        if active:
            binding = ledger["generations"][active]["binding"]
            snapshot_authority = dict(previous, resource_binding_id=previous["binding_id"],
                                      capture_generation=str(previous["capture_generation"]))
            del snapshot_authority["binding_id"]
            if (binding["generation_id"] == active and binding["authority"] == snapshot_authority
                    and binding["mirror_id"] in evidence["target_fence"]["mirror_receipts"]):
                ledger["generations"][active].update(state="abandoned", released_at=utc_now().isoformat())
                ledger["active"] = None
        state.update(authority, applied_revision=None, observed_at=None, stop_ack=None,
                     published_scope=scope["published_scope"], desired="stopped" if command["kind"] == "stop" else "configured",
                     allocation={**pending, "evidence": evidence})
        save_binding(session, state)
        desired_scope = read_published_scope(session, source_id)
        if desired_scope != scope["published_scope"]:
            # Make registry changes effective before the reserved command can run.
            _advance_intent(session, state, source, desired_scope)
        return command


def replacement_blocks_lifecycle(session, state):
    if state.get("pending_replacement"):
        return True
    command = state.get("allocation", {}).get("command", {})
    if command.get("kind") != "replace_owner":
        return False
    retired = state["allocation"].get("deleted_replacement")
    if (retired and retired["operation_id"] == command["operation_id"]
            and retired["mirror_id"] == command["replacement"]["scope"]["submission"]["mirror_id"]):
        return False
    recovery = session.get(RecoveryRow, command["operation_id"])
    if recovery is None or recovery.journal.get("state") != "applied":
        return True
    receipt = recovery.journal.get("publication_receipt", {})
    submission = command["replacement"]["scope"]["submission"]
    authority = {key: command[key] for key in AUTHORITY_KEYS if key != "binding_id"}
    authority.update(resource_binding_id=command["binding_id"], capture_generation=submission["capture_generation"])
    return any(receipt.get(key) != value for key, value in dict(
        authority=authority, generation_id=submission["generation_id"], history_epoch=submission["history_epoch"]
    ).items())


def _replacement_scope(session, source, operation_id, previous, scope):
    recovery = session.get(RecoveryRow, operation_id)
    if recovery is None or recovery.source_id != source.id:
        raise SourceCaptureControlConflict()
    journal = recovery.journal
    submission = journal.get("submission_command")
    if (journal.get("state") not in {"submitting", "dispatched"} or not journal.get("replacement_epoch")
            or not journal.get("generation_id") or not journal.get("request", {}).get("actor_user_id")
            or submission != dict(operation_id=operation_id, kind="replacement", mirror_id=recovery.mirror_id,
                                  source_id=source.id, history_epoch=journal["replacement_epoch"], empty=True,
                                  origin="recovery", capture_generation=str(previous["capture_generation"] + 1),
                                  generation_id=journal["generation_id"])
            or journal.get("capture_generation") != submission["capture_generation"]):
        raise SourceCaptureControlConflict()

    mirror_ids = sorted(table["mirror_id"] for table in scope["published_scope"])
    affected = sorted(table["mirror_id"] for table in included_tables(scope["published_scope"]))
    if affected != [recovery.mirror_id]:
        raise SourceCaptureControlConflict()
    gates = {gate.mirror_id: gate for gate in session.scalars(
        select(HistoryGateRow).where(HistoryGateRow.mirror_id.in_(mirror_ids))
        .order_by(HistoryGateRow.mirror_id).with_for_update().execution_options(populate_existing=True)
    )}
    loss = session.get(HistoryInvalidationRow, operation_id, with_for_update=True)
    if (loss is None or loss.reason != "history_loss" or loss.status != "applied"
            or [change["mirror_id"] for change in loss.transitions] != affected
            or any(gates.get(change["mirror_id"]) is None
                   or gates[change["mirror_id"]].status != "available"
                   or gates[change["mirror_id"]].history_epoch != change["history_epoch"] for change in loss.transitions)
            or gates[recovery.mirror_id].history_epoch != journal["replacement_epoch"]):
        raise SourceCaptureControlConflict()

    mirrors = {mirror.id: mirror for mirror in session.scalars(select(MirrorRow).where(MirrorRow.source_id == source.id))}
    if sorted(mirrors) != mirror_ids:
        raise SourceCaptureControlConflict()
    inventory = {
        mirror_id: dict(published_generation_id=mirrors[mirror_id].state.get("published_generation_id"),
                        capture_generation=mirrors[mirror_id].state.get("capture_generation"),
                        history_epoch=gates[mirror_id].history_epoch if mirror_id in gates else None,
                        history_status=gates[mirror_id].status if mirror_id in gates else None)
        for mirror_id in mirror_ids
    }
    return dict(scope, recovery_request_identity=recovery.identity, submission=submission,
                history_loss=loss.transitions, target_inventory=inventory)


def _replacement_context(session, source, state, operation_id, profile):
    if (session is None or state is None or source.engine != "postgresql" or state["desired"] != "configured"
            or state["owner_epoch"] <= 0 or not state["runtime_instance_id"]
            or type(state["capture_generation"]) is not int or state["capture_generation"] < 1):
        raise SourceCaptureControlConflict()
    previous, scope = _allocation_context(session, source, state, profile, ordinary_takeover=False)
    return previous, _replacement_scope(session, source, operation_id, previous, scope)


def replace_owner(*, source_id, operation_id, signed_proof, signals, before_observation=None):
    """Consume a committed whole-Source recovery intent through a separate signed protocol."""
    if (not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", operation_id)
            or not isinstance(signed_proof, str) or not signed_proof or not signed_proof.isascii()
            or signals.verifier is None):
        raise SourceCaptureControlConflict()
    request_digest = sha256(signed_proof.encode()).hexdigest()
    with source_control_transaction(source_id) as (session, source):
        existing = load_operation(session, operation_id)
        state = load_binding(session, source_id)
        if existing is not None:
            command = existing["command"]
            if (command["kind"] != "replace_owner" or command["source_id"] != source_id
                    or command["runtime_instance_id"] != signals.runtime_instance_id
                    or command["replacement"]["request_digest"] != request_digest
                    or command["replacement"]["scope"]["profile"] != signals.scope):
                raise SourceCaptureControlConflict()
            if existing["evidence"] is not None:
                return command
        else:
            previous, scope = _replacement_context(session, source, state, operation_id, signals.scope)
            if (replacement_blocks_lifecycle(session, state)
                    or state.get("pending_allocation", {}).get("previous_authority") == previous):
                raise SourceCaptureControlConflict()
            authority = dict(previous, owner_epoch=previous["owner_epoch"] + 1,
                             capture_generation=previous["capture_generation"] + 1,
                             control_revision=previous["control_revision"] + 1,
                             runtime_instance_id=signals.runtime_instance_id)
            claims = signals.verifier.verify(signed_proof, purpose="replacement_owner", authority=authority,
                                             scope=scope, operation_id=operation_id)
            if json.dumps({key: claims.get(key) for key in ("previous_authority", "authority", "scope")}, sort_keys=True) != json.dumps(
                dict(previous_authority=previous, authority=authority, scope=scope), sort_keys=True
            ):
                raise SourceCaptureControlConflict()
            issuance = persist_audit_event(
                actor_user_id=None, actor_token_id=None, resource_type="source", resource_id=source_id,
                action="source.capture_replacement_reserved", result="success", session=session,
                detail=dict(operation_id=operation_id, recovery_request_identity=scope["recovery_request_identity"],
                            previous_authority=previous, authority=authority, request_digest=request_digest),
            )
            command = _command({**state, **authority}, source, operation_id)
            command.update(kind="replace_owner", replacement=dict(previous_authority=previous, scope=scope,
                           request_digest=request_digest, issuance_audit_id=issuance.id))
            save_operation(session, command)
            state["pending_replacement"] = operation_id
            save_binding(session, state)

    with source_control_transaction(source_id) as (session, source):
        operation = load_operation(session, operation_id)
        if operation is None or operation["command"] != command:
            raise SourceCaptureControlConflict()
        if operation["evidence"] is not None:
            return command
        state = load_binding(session, source_id)
        previous, scope = _replacement_context(session, source, state, operation_id, signals.scope)
        reservation = command["replacement"]
        if (state.get("pending_replacement") != operation_id or previous != reservation["previous_authority"]
                or scope != reservation["scope"]):
            raise SourceCaptureControlConflict()
        if before_observation is not None:
            before_observation()
        observation = signals.replacement_observation(command, signed_proof)
        applied = persist_audit_event(
            actor_user_id=None, actor_token_id=None, resource_type="source", resource_id=source_id,
            action="source.capture_replacement_promoted", result="success", session=session,
            detail=dict(operation_id=operation_id, issuance_audit_id=reservation["issuance_audit_id"],
                        request_digest=request_digest, observation_digest=observation["observation_digest"]),
        )
        evidence = dict(observation, audit_id=applied.id)
        save_operation(session, command, evidence)
        state.pop("pending_replacement")
        state.pop("pending_allocation", None)
        state.update({key: command[key] for key in AUTHORITY_KEYS}, applied_revision=command["control_revision"],
                     observed_at=evidence["observed_at"], stop_ack=None,
                     allocation=dict(command=command, evidence=evidence))
        promote_replacement_binding(session, state, command)
        return command


def capture_status(source_id: str) -> dict:
    with source_control_transaction(source_id) as (session, source):
        state = load_binding(session, source_id)
        readiness = [
            {
                "key": "runtime_qualification",
                "result": "unknown",
                "expected": "Qualified profile, exclusive owner and independent safety evidence",
                "observed": None,
                "observed_at": None,
                "owner": "deployer",
                "action": "Install and qualify the independent capture control agent",
            }
        ]
        if state is None:
            return {
                "source_id": source_id,
                "binding_id": None,
                "profile_id": None,
                "availability": "disabled",
                "control": None,
                "operations": [],
                "readiness": readiness,
            }
        stopped = state["desired"] == "stopped" and state["stop_ack"] is not None
        return {
            "source_id": source_id,
            "binding_id": state["binding_id"],
            "profile_id": None,
            "readiness": readiness,
            "availability": "disabled" if stopped else "unknown",
            "control": {key: value for key, value in state.items()
                        if key not in {"allocation", "pending_allocation", "pending_replacement", "published_scope",
                                       "incremental_snapshots", "table_stops", "scope_fence"}},
            "operations": [
                {
                    **{key: value for key, value in op["command"].items() if key not in {"published_scope", "replacement"}},
                    "state": "applied" if op["evidence"] else (
                        "pending" if op["command"]["control_revision"] == state["control_revision"]
                        else "superseded"
                    ),
                }
                for op in list_operations(session, source_id)
            ],
        }


def record_applied_evidence(
    *, source_id: str, operation_id: str, evidence: dict, refresh_table_exclusions=False
) -> dict:
    """Accept only exact-authority independent stop/installation observations."""
    with source_control_transaction(source_id) as (session, source):
        state = load_binding(session, source_id)
        operation = load_operation(session, operation_id)
        if state is None or operation is None:
            raise SourceCaptureControlConflict()
        command = operation["command"]
        if command["kind"] != "stop" and replacement_blocks_lifecycle(session, state):
            raise SourceCaptureControlConflict()
        if (command["kind"] == "reconcile"
                and command.get("published_scope") != read_dispatch_scope(session, source_id, state=state)):
            raise SourceCaptureControlConflict()
        if any(
            command[key] != state[key] or evidence.get(key) != state[key]
            for key in AUTHORITY_KEYS
        ):
            raise SourceCaptureControlConflict()
        if evidence.get("operation_id") != operation_id:
            raise SourceCaptureControlConflict()
        required = {"observed_at", "target_fence_ref", "owner_exclusion_ref"}
        if command["kind"] == "stop":
            required |= {
                "retired_commands_rejected_ref",
                "task_stopped_ref",
                "source_session_stopped_ref",
                "inflight_drained_ref",
            }
        else:
            required |= {"credential_installed_ref", "credential_revoked_ref"}
        allowed = set(AUTHORITY_KEYS) | required | {"operation_id"}
        exclusions = table_exclusion_refs(command.get("published_scope", []), evidence.get("table_exclusions", []))
        if "table_exclusions" in evidence and command["kind"] == "reconcile":
            allowed.add("table_exclusions")
        if set(evidence) != allowed or any(
            not isinstance(evidence.get(key), str) or not evidence[key].strip()
            for key in required
        ):
            raise SourceCaptureControlConflict()
        try:
            observed = datetime.fromisoformat(evidence["observed_at"])
        except ValueError:
            raise SourceCaptureControlConflict() from None
        if (
            observed.tzinfo is None
            or observed > utc_now()
            or observed < datetime.fromisoformat(command["requested_at"])
        ):
            raise SourceCaptureControlConflict()
        if operation["evidence"] is not None:
            if refresh_table_exclusions and command["kind"] == "reconcile" and exclusions:
                if state["applied_revision"] != state["control_revision"]:
                    raise SourceCaptureControlConflict()
                _record_table_stops(session, state, command, evidence, exclusions)
                return evidence
            if operation["evidence"] != evidence:
                raise SourceCaptureControlConflict()
            return operation["evidence"]
        # No agent is assigned in the foundation slice. Reconciliation must not
        # manufacture an installed owner or credential authority.
        if command["kind"] != "stop" and state["runtime_instance_id"] is None:
            raise SourceCaptureControlConflict()
        save_operation(session, command, evidence)
        state["applied_revision"] = state["control_revision"]
        state["observed_at"] = evidence["observed_at"]
        state["stop_ack"] = evidence if command["kind"] == "stop" else None
        if state["stop_ack"] and state["owner_epoch"] > 0 and state["runtime_instance_id"]:
            ledger = state.get("incremental_snapshots", {})
            active = ledger.get("active")
            scan = ledger.get("generations", {}).get(active)
            if scan:
                old = scan["binding"]
                excluded = any(not entry["included"] and entry["mirror_id"] == old["mirror_id"]
                               and entry["table_identity"] == old["table_identity"]
                               and entry["mirror_revision"] > old["mirror_revision"]
                               for entry in command.get("published_scope", []))
                if excluded and old["generation_id"] == active and old["authority"]["source_id"] == source_id:
                    scan.update(state="abandoned", released_at=evidence["observed_at"])
                    ledger["active"] = None
        save_binding(session, state)
        projected_scope = command.get("published_scope")
        if (command["kind"] == "stop" and state["desired"] == "stopped"
                and state["runtime_instance_id"] and state["owner_epoch"] > 0
                and projected_scope and projected_scope == read_published_scope(session, source_id)):
            record_mirror_stop_evidence(session, command, evidence)
        elif exclusions:
            _record_table_stops(session, state, command, evidence, exclusions)
        return evidence


def _record_table_stops(session, state, command, evidence, exclusions):
    stops = state.setdefault("table_stops", {"operation_id": command["operation_id"], "confirmed": []})
    if stops["operation_id"] != command["operation_id"]:
        raise SourceCaptureControlConflict()
    record_mirror_stop_evidence(session, command, evidence, exclusions=exclusions)
    stops["confirmed"] = sorted(set(stops["confirmed"]).union(exclusions))
    save_binding(session, state)
