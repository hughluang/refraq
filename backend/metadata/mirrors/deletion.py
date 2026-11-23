"""Admission evidence and restricted target cleanup for a single retired Mirror."""

from dataclasses import asdict
import json

from sqlalchemy import text

from backend.metadata.capture.store import list_operations, load_binding, load_operation, save_binding
from backend.metadata.mirrors.errors import MirrorError
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.store import MemoryMirrorStore
from backend.metadata.mirrors.types import Authority


def _was_dispatched(command, mirror_id):
    # Unassigned commands cannot install a target fence or start a producer.
    return (command.get("owner_epoch", 0) > 0 and command.get("runtime_instance_id") is not None
            and any(entry.get("mirror_id") == mirror_id for entry in command.get("published_scope", [])))


def _fence(command, receipt=None):
    authority = Authority(
        source_id=command["source_id"], resource_binding_id=command["binding_id"],
        capture_generation=str(command["capture_generation"]), runtime_instance_id=command["runtime_instance_id"],
        owner_epoch=command["owner_epoch"], control_revision=command["control_revision"],
        credential_revision=command["credential_revision"],
    )
    return dict(operation_id=command["operation_id"], authority=asdict(authority), receipt=receipt)


def deletion_proof(session, mirror, operations):
    """Return None only when durable management records exclude any runtime dispatch."""
    mid, source_id = mirror["id"], mirror["source_id"]
    database = None if isinstance(session, MemoryMirrorStore) else session
    state = load_binding(database, source_id) or {}
    ledger = state.get("incremental_snapshots", {})
    scans = ledger.get("generations", {})
    active = ledger.get("active")
    if active:
        binding = scans.get(active, {}).get("binding", {})
        if not binding.get("mirror_id") or binding["mirror_id"] == mid:
            raise MirrorError("MIRROR_SNAPSHOT_IN_USE", 409)
    has_work = (mirror.get("published_generation_id") or mirror.get("history_epoch")
                or any(op.get("allocation") or op.get("publication_receipt") or
                       op.get("replacement_generation_id") for op in operations)
                or any(scan.get("binding", {}).get("mirror_id") == mid for scan in scans.values())
                or (database is not None and database.get(HistoryGateRow, mid) is not None))
    if not has_work:
        commands = [op["command"] for op in list_operations(database, source_id)]
        commands.extend(reservation.get("command", {}) for reservation in
                        (state.get("pending_allocation") or {}, state.get("allocation") or {}))
        if not any(_was_dispatched(command, mid) for command in [*commands, state]):
            return None

    control = mirror["control"]
    ack = control.get("stop_ack") or {}
    disable = next((op for op in operations if op["id"] == ack.get("operation_id")), {})
    source_operation = ack.get("source_operation_id")
    if (mirror["status"] != "disabled" or control.get("applied_revision") != control["control_revision"]
            or disable.get("control_revision") != control["control_revision"]
            or disable.get("kind") != "disable" or disable.get("state") != "applied"
            or source_operation not in disable.get("observed_evidence_refs", [])):
        raise MirrorError("MIRROR_STOP_UNCONFIRMED", 409)
    observed = load_operation(database, source_operation)
    if not observed or not observed["evidence"]:
        raise MirrorError("MIRROR_STOP_UNCONFIRMED", 409)
    command = observed["command"]
    if (command.get("source_id") != source_id or state.get("applied_revision") != command["control_revision"]
            or any(command.get(key) != state.get(key) for key in (
                "control_revision", "owner_epoch", "runtime_instance_id", "binding_id", "capture_generation", "credential_revision"))
            or not any(entry["mirror_id"] == mid and entry["included"] is False
                       and entry["mirror_revision"] == control["control_revision"]
                       and entry["table_identity"] == mirror["table_identity"] for entry in command["published_scope"])):
        raise MirrorError("MIRROR_STOP_UNCONFIRMED", 409)

    fences = [_fence(command)]
    # Some terminal stop observers reverify the existing allocation fence and drain
    # its producer. Per-table exclusion requires the fence for its own command.
    allocation = state.get("allocation") or {}
    receipt = allocation.get("evidence", {}).get("target_fence", {}).get("mirror_receipts", {}).get(mid)
    if command["kind"] == "stop" and receipt:
        assigned = allocation["command"]
        if all(assigned.get(key) == command[key] for key in
               ("source_id", "binding_id", "capture_generation", "owner_epoch", "runtime_instance_id")):
            fences.append(_fence(assigned, receipt))
    return dict(source_id=source_id, table_identity=mirror["table_identity"], fences=fences,
                disable_operation_id=disable["id"], control_revision=control["control_revision"],
                source_operation_id=source_operation,
                allow_absent=not (mirror.get("published_generation_id") or receipt
                                  or any(op.get("allocation", {}).get("observed") or op.get("publication_receipt")
                                         for op in operations)))


def retire_replacement(session, mirror):
    """Keep the active Source owner's replacement settlement after the Mirror is removed."""
    if isinstance(session, MemoryMirrorStore):
        return
    state = load_binding(session, mirror["source_id"]) or {}
    allocation = state.get("allocation") or {}
    command = allocation.get("command", {})
    submission = command.get("replacement", {}).get("scope", {}).get("submission", {})
    if command.get("kind") != "replace_owner" or submission.get("mirror_id") != mirror["id"]:
        return
    # Source reconciliation must still be able to admit a later owner after the
    # registered replacement is deleted, including a build abandoned by its stop.
    allocation["deleted_replacement"] = dict(mirror_id=mirror["id"], operation_id=command["operation_id"],
                                              delete_operation_id=mirror["deletion_operation_id"])
    save_binding(session, state)


class TargetDeletion:
    def __init__(self, engine):
        self.engine = engine

    def seal(self, mirror_id, operation_id, proof):
        params = dict(mid=mirror_id, op=operation_id, proof=json.dumps(proof))
        with self.engine.begin() as connection:
            status = connection.execute(text(
                "SELECT source_mirror_state.seal_deletion(:mid, :op, CAST(:proof AS jsonb))"
            ), params).scalar_one()
            if status == "pinned":
                raise MirrorError("MIRROR_READERS_IN_USE", 409)
            if status not in ("sealed", "completed"):
                raise MirrorError("MIRROR_STOP_UNCONFIRMED", 409)

    def purge(self, mirror_id, operation_id, proof):
        params = dict(mid=mirror_id, op=operation_id, proof=json.dumps(proof))
        with self.engine.begin() as connection:
            connection.execute(text(
                "SELECT source_mirror_state.purge_mirror(:mid, :op, CAST(:proof AS jsonb))"
            ), params)
