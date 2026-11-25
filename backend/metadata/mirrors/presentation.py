"""Operations projection of a Mirror: lifecycle evidence, waits, readiness and progress.

Every read takes the Mirror store it runs against, so Console reads, fleet reads and
diagnostics project the same evidence from the store they were given.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.core.time import utc_now
from backend.metadata.capture.configuration import SnapshotWindow, snapshot_dispatch_allowed
from backend.metadata.capture.store import load_binding
from backend.metadata.mirrors import lifecycle
from backend.metadata.mirrors.lifecycle import current_open, open_evidence
from backend.metadata.mirrors.schemas import Operation
from backend.metadata.mirrors.types import Authority

__all__ = ["SourceLifecycle", "diagnostic_scope", "present", "snapshot_progress", "source_lifecycle"]


def snapshot_progress(snapshot, stage):
    if stage is None:
        return None
    generation = snapshot["binding"]["generation_id"]
    sample = snapshot.get("progress_sample") or {}
    scan = snapshot.get("scan")
    evidence = snapshot["completion"] if stage == "catching_up" else scan or sample
    milliseconds = evidence.get("timestamp")
    observed_at = (datetime.fromtimestamp(milliseconds / 1000, UTC)
                   if type(milliseconds) is int and 0 <= milliseconds < 253402300800000 else None)
    # Older ledgers mixed byte counters into lifecycle samples without retaining
    # their measurement time. Preserve those values with unknown provenance.
    measured = snapshot.get("byte_sample") or sample
    scanned_bytes = measured.get("scanned_bytes")
    total = measured.get("scan_total_bytes")
    percent = 100 if scan else None
    if not scan and scanned_bytes is not None and total:
        percent = 100 * scanned_bytes / total
    byte_time = measured.get("timestamp") if snapshot.get("byte_sample") else None
    bytes_observed_at = (datetime.fromtimestamp(byte_time / 1000, UTC)
                         if type(byte_time) is int and 0 <= byte_time < 253402300800000 else None)
    return dict(stage=stage, generation_id=generation, notification_offset=evidence["offset"],
                observed_at=observed_at, scanned_bytes=scanned_bytes, scan_percent=percent, scan_complete=bool(scan),
                byte_notification_offset=measured.get("offset") if snapshot.get("byte_sample") else None,
                bytes_observed_at=bytes_observed_at)


def _slot_binding(store, session, source_id, state):
    ledger = state.get("incremental_snapshots", {})
    active = ledger.get("active")
    if not active:
        return None
    binding = ledger.get("generations", {}).get(active, {}).get("binding", {})
    if (not binding.get("allocation_operation_id") or binding.get("generation_id") != active
            or binding.get("authority", {}).get("source_id") != source_id):
        return None
    holder = store.get(session, binding.get("mirror_id"))
    if (not holder or holder["source_id"] != source_id
            or any(binding.get(key) != holder[key] for key in ("table_identity", "qualified_table"))):
        return None
    return binding


def _publication_wait(store, session, state, scope):
    if not state.get("incremental_snapshots", {}).get("generations"):
        return None
    if scope != state.get("published_scope", []):
        return None
    candidates = [scan for scan in state["incremental_snapshots"]["generations"].values()
                  if scan["state"] == "catching_up"
                  and lifecycle.current_authority(state, Authority(**scan["binding"]["authority"]), scope)]
    pending = store.pending_opens(session, {scan["binding"]["mirror_id"] for scan in candidates})
    for scan in candidates:
        binding = scan["binding"]
        operation = next((op for op in pending[binding["mirror_id"]]
                          if op["id"] == binding["allocation_operation_id"]), None)
        if operation is None:
            continue
        holder = store.get(session, binding["mirror_id"])
        if holder and open_evidence(holder, [operation], state, scope).snapshot == scan:
            return dict(mirror_id=holder["id"], qualified_table=holder["qualified_table"])
    return None


def _wait_reason(store, session, mirror, pending, state):
    if not mirror["enabled"]:
        return None
    source_id = mirror["source_id"]
    source = store.source(session, source_id)
    if source is None:
        return None
    if source.status == "disabled":
        return "source_disabled", "Enable the Source to allow capture."
    if not source.capture_credential_ciphertext:
        return "capture_credential_missing", "Configure the Source capture credential."
    allocation = state.get("allocation", {})
    owner = allocation.get("command", {})
    current_owner = owner and all(owner.get(key) == state.get(key) for key in (
        "source_id", "owner_epoch", "runtime_instance_id", "capture_generation",
    ))
    scope = allocation.get("scope") or owner.get("replacement", {}).get("scope", {})
    approved = scope.get("profile", {}).get("tables")
    if current_owner and approved is not None and mirror["qualified_table"] not in approved:
        return "table_unqualified", "Qualify this table in the assigned Source capture profile."
    if not source.snapshot_window or owner.get("kind") == "replace_owner":
        return None
    if pending:
        generation = (pending.get("allocation") or {}).get("generation_id")
        snapshot = state.get("incremental_snapshots", {}).get("generations", {}).get(generation, {})
        if (snapshot.get("state") in (None, "awaiting_dispatch", "waiting_window")
                and not snapshot_dispatch_allowed(SnapshotWindow.model_validate(source.snapshot_window), utc_now())):
            return "snapshot_window_closed", "Wait for the Source snapshot window to open."
    return None


def _lifecycle_view(store, session, mirror, operations, context):
    evidence = open_evidence(mirror, operations, context.state, context.scope)
    pending = evidence.pending
    progress = snapshot_progress(evidence.snapshot, evidence.stage)
    reason = _wait_reason(store, session, mirror, pending, context.state)
    binding = context.slot
    holder = None
    if pending and not progress:
        if binding and binding["allocation_operation_id"] != pending["id"]:
            holder = dict(mirror_id=binding["mirror_id"], qualified_table=binding["qualified_table"])
            if reason is None:
                if holder["mirror_id"] == mirror["id"]:
                    reason = "own_snapshot_slot_busy", "Wait for the runtime to release this table's abandoned scan."
                else:
                    reason = "snapshot_slot_busy", "Wait for the current Source snapshot to finish."
    queued = pending and mirror["id"] not in context.included
    publication_wait = context.publication_wait if queued else None
    if reason is None and publication_wait:
        reason = "publication_pending", "Wait for the preceding table's verified publication."
    eligible = reason is None or reason[0] in {"snapshot_window_closed", "snapshot_slot_busy", "own_snapshot_slot_busy", "publication_pending"}
    admitted = eligible and evidence.admitted
    profile = deepcopy(mirror["profile"])
    readiness = deepcopy(mirror["readiness"])
    if admitted:
        profile = {"qualification": "qualified"}
        readiness = [dict(key="capture_admission", result="pass", expected=None,
                          observed="Current table generation verified and Source capture revision applied", observed_at=context.state.get("observed_at"),
                          owner="runtime", action="")]
    if reason:
        key, action = reason
        if not admitted:
            readiness = [item for item in readiness if item["key"] != "capture_admission"]
        readiness.append(dict(key=key, result="fail", expected=None, observed=None, observed_at=None,
                              owner="deployer", action=action))
    blocker = mirror.get("blocker") if mirror["enabled"] else None
    if blocker:
        cause = blocker["cause"]
        action = {"permission": "Restore the table read permission.", "schema": "Verify the table schema and key.",
                  "continuity": "Verify log coverage across the interrupted interval."}[cause]
        readiness.append(dict(key=f"mirror_{cause}_blocked", result="fail", expected=None, observed=None,
                              observed_at=blocker["last_checked_at"], owner="runtime", action=action))
    if evidence.snapshot is not None and evidence.snapshot["state"] == "blocked":
        readiness.append(dict(key="incremental_snapshot_blocked", result="fail", expected=None,
                              observed="The current snapshot could not be verified.", observed_at=None,
                              owner="deployer", action="Resolve the snapshot evidence conflict before retrying capture."))
    return dict(status=evidence.status, progress=progress, snapshot_slot_holder=holder, publication_wait=publication_wait,
                profile=profile, readiness=readiness)


@dataclass(frozen=True)
class SourceLifecycle:
    state: dict
    scope: list
    included: set[str]
    slot: dict | None
    publication_wait: dict | None


def source_lifecycle(store, session, source_id):
    """Read the Source's capture state with its dispatch scope, snapshot slot and publication wait."""
    state = load_binding(store.database(session), source_id) or {}
    scope = lifecycle.read_dispatch_scope(store, session, source_id, state=state) if state else []
    return SourceLifecycle(state, scope, {entry["mirror_id"] for entry in scope if entry["included"]},
                           _slot_binding(store, session, source_id, state),
                           _publication_wait(store, session, state, scope))


def present(store, session, mirror, context):
    """Project a stored Mirror with its current lifecycle evidence and public operations."""
    operations = store.ops(session, mirror["id"])
    result = deepcopy(mirror)
    # Mirrors stored before engine expansion could only exist on PostgreSQL Sources.
    result.setdefault("source_engine", "postgresql")
    result.pop("blocker", None)
    result.pop("deletion_reservation", None)
    gate = store.history_gate(session, mirror["id"])
    result["history_epoch"] = store.history_epoch(session, mirror) if mirror["published_generation_id"] else None
    if gate is None or gate.status != "available" or gate.history_epoch != mirror.get("history_epoch"):
        result["retained_lower_bound"] = result["committed_upper_bound"] = None
    result.update(_lifecycle_view(store, session, mirror, operations, context))
    result["operations"] = []
    for op in sorted(operations, key=lambda item: (item["requested_at"], item["id"])):
        public = {key: op[key] for key in Operation.model_fields}
        certificate = op.get("publication_receipt", {}).get("certificate_ref")
        if op["state"] == "applied" and certificate:
            public["observed_evidence_refs"] = list(dict.fromkeys([*public["observed_evidence_refs"], certificate]))
        result["operations"].append(public)
    return result


def diagnostic_scope(*, mirror_store, source_store):
    """Read registry and current authority without lifecycle or network operations."""
    rows, bindings, operations = mirror_store.registry_rows(source_store)
    pending = {}
    for operation in operations:
        if operation["kind"] == "open" and operation["state"] == "pending":
            pending.setdefault(operation["mirror_id"], []).append(operation)
    for mirror in rows:
        opened = current_open(mirror, pending.get(mirror["id"], []))
        allocation = opened.get("allocation") if opened and opened["state"] == "pending" else None
        mirror["allocated_generation_id"] = allocation["generation_id"] if allocation else None
    return rows, bindings
