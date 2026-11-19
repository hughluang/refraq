"""Durable Source capture intent; no external provisioning occurs in this module."""

from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.db import session_scope
from backend.core.time import utc_now
from backend.metadata.capture.store import (
    list_operations,
    load_binding,
    load_operation,
    save_binding,
    save_operation,
)
from backend.metadata.errors import SourceCaptureControlConflict, SourceNotFound
from backend.metadata.mirrors.service import read_published_scope
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


def profile_matches_scope(profile_scope, published_scope):
    desired = included_tables(published_scope)
    configured = profile_scope.get("tables", [])
    return bool(desired) and len(configured) == len(desired) and sorted(configured) == sorted(
        table["qualified_table"] for table in desired
    )


def _desired(source, published_scope):
    if source.status == "active" and source.capture_credential_ciphertext and included_tables(published_scope):
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
    state.update(control_revision=state["control_revision"] + 1,
                 credential_revision=source.capture_revision, stop_ack=None,
                 applied_revision=None, observed_at=None, published_scope=published_scope,
                 desired=_desired(source, published_scope))
    command = _command(state, source, f"cop_{uuid4().hex}")
    save_binding(session, state)
    save_operation(session, command)
    return command


def reconcile_published_scope(source_id):
    """Commit the current scope and corresponding command before runtime dispatch."""
    with source_control_transaction(source_id) as (session, source):
        state = load_binding(session, source_id)
        if state is None:
            return
        scope = read_published_scope(session, source_id)
        if scope == state.get("published_scope", []) and state["desired"] == _desired(source, scope):
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


def allocate_owner(*, source_id, runtime_instance_id, operation_id, signed_proof,
                   verifier, scope):
    """Allocate a new term only against signed current exclusion and fence facts."""
    with source_control_transaction(source_id) as (session, source):
        state = load_binding(session, source_id)
        if (state is None or state.get("desired") not in {"configured", "stopped"}
                or not runtime_instance_id or load_operation(session, operation_id)):
            raise SourceCaptureControlConflict()
        if state["desired"] == "configured":
            published_scope = read_published_scope(session, source_id)
            if (published_scope != state.get("published_scope")
                    or not profile_matches_scope(scope, published_scope)):
                raise SourceCaptureControlConflict()
        previous = {key: state[key] for key in AUTHORITY_KEYS}
        authority = {**previous, "owner_epoch": state["owner_epoch"] + 1,
                     "runtime_instance_id": runtime_instance_id,
                     "control_revision": state["control_revision"] + 1}
        claims = verifier.verify(signed_proof, purpose="owner_allocation", authority=authority,
                                 scope=scope, operation_id=operation_id)
        if (claims.get("previous_authority") != previous
                or claims.get("facts") != {"old_agent_excluded": True,
                                           "old_tasks_excluded": True,
                                           "target_fence_installed": True}):
            raise SourceCaptureControlConflict()
        state.update(authority, applied_revision=None, observed_at=None, stop_ack=None,
                     allocation={"proof": signed_proof, "scope": scope})
        command = _command(state, source, operation_id)
        save_binding(session, state)
        save_operation(session, command)
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
            "control": {key: value for key, value in state.items() if key not in {"allocation", "published_scope"}},
            "operations": [
                {
                    **{key: value for key, value in op["command"].items() if key != "published_scope"},
                    "state": "applied" if op["evidence"] else (
                        "pending" if op["command"]["control_revision"] == state["control_revision"]
                        else "superseded"
                    ),
                }
                for op in list_operations(session, source_id)
            ],
        }


def pending_commands(source_id: str) -> tuple[dict, ...]:
    """Return the current durable command; acceptance never marks it applied."""
    with source_control_transaction(source_id) as (session, source):
        state = load_binding(session, source_id)
        if state is None:
            return ()
        return tuple(
            op["command"]
            for op in list_operations(session, source_id)
            if op["evidence"] is None
            and op["command"]["control_revision"] == state["control_revision"]
        )


def record_applied_evidence(
    *, source_id: str, operation_id: str, evidence: dict
) -> dict:
    """Accept only exact-authority independent stop/installation observations."""
    with source_control_transaction(source_id) as (session, source):
        state = load_binding(session, source_id)
        operation = load_operation(session, operation_id)
        if state is None or operation is None:
            raise SourceCaptureControlConflict()
        command = operation["command"]
        if (command["kind"] == "reconcile"
                and command.get("published_scope") != read_published_scope(session, source_id)):
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
        save_binding(session, state)
        return evidence
