"""Capture binding and command persistence in the Source transaction."""

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.metadata.errors import SourceCaptureControlConflict
from backend.metadata.mirrors.status_projection import refresh_source_status
from backend.metadata.models import SourceCaptureBindingRow, SourceCaptureOperationRow
from backend.metadata.sources.store import get_source_store


def load_binding(session: Session | None, source_id: str) -> dict | None:
    if session is None:
        return deepcopy(get_source_store().capture_bindings.get(source_id))
    row = session.get(SourceCaptureBindingRow, source_id)
    return deepcopy(row.state) if row else None


def save_binding(session: Session | None, state: dict) -> None:
    existing = load_binding(session, state["source_id"])
    if existing is not None and any(
        existing[key] != state[key]
        for key in ("source_id", "binding_id", "capture_generation")
    ):
        raise SourceCaptureControlConflict()
    _write_binding(session, state)


def promote_replacement_binding(session: Session, state: dict, command: dict) -> None:
    existing = load_binding(session, command["source_id"])
    operation = load_operation(session, command["operation_id"])
    if (existing is None or operation is None or operation["command"] != command
            or command["kind"] != "replace_owner" or operation["evidence"] is None
            or existing.get("pending_replacement") != command["operation_id"]
            or any(existing[key] != value for key, value in command["replacement"]["previous_authority"].items())
            or any(state[key] != command[key] for key in command["replacement"]["previous_authority"])
            or state["binding_id"] != existing["binding_id"]
            or state["capture_generation"] != existing["capture_generation"] + 1
            or state["owner_epoch"] != existing["owner_epoch"] + 1):
        raise SourceCaptureControlConflict()
    _write_binding(session, state)


def _write_binding(session: Session | None, state: dict) -> None:
    if session is None:
        get_source_store().capture_bindings[state["source_id"]] = deepcopy(state)
        return
    row = session.get(SourceCaptureBindingRow, state["source_id"])
    if row is None:
        row = SourceCaptureBindingRow(
            source_id=state["source_id"],
            binding_id=state["binding_id"],
            state=state,
        )
        session.add(row)
    else:
        row.state = deepcopy(state)
    session.flush()
    refresh_source_status(session, state["source_id"])


def load_operation(session: Session | None, operation_id: str) -> dict | None:
    if session is None:
        return deepcopy(get_source_store().capture_operations.get(operation_id))
    row = session.get(SourceCaptureOperationRow, operation_id)
    if row is None:
        return None
    return {"command": deepcopy(row.command), "evidence": deepcopy(row.evidence)}


def save_operation(
    session: Session | None, command: dict, evidence: dict | None = None
) -> None:
    existing = load_operation(session, command["operation_id"])
    if existing is not None:
        if existing["command"] != command or (
            existing["evidence"] is not None and existing["evidence"] != evidence
        ):
            raise SourceCaptureControlConflict()
    if session is None:
        get_source_store().capture_operations[command["operation_id"]] = deepcopy(
            {"command": command, "evidence": evidence}
        )
        return
    row = session.get(SourceCaptureOperationRow, command["operation_id"])
    if row is None:
        row = SourceCaptureOperationRow(
            operation_id=command["operation_id"],
            source_id=command["source_id"],
            command=command,
            evidence=evidence,
        )
        session.add(row)
    else:
        row.evidence = deepcopy(evidence)
    session.flush()


def list_operations(session: Session | None, source_id: str) -> list[dict]:
    if session is None:
        operations = list(get_source_store().capture_operations.values())
    else:
        operations = [
            {"command": row.command, "evidence": row.evidence}
            for row in session.scalars(
                select(SourceCaptureOperationRow).where(
                    SourceCaptureOperationRow.source_id == source_id
                )
            )
        ]
    return deepcopy(
        sorted(
            (op for op in operations if op["command"]["source_id"] == source_id),
            key=lambda op: op["command"]["control_revision"],
        )
    )
