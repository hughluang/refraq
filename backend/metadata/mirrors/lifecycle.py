"""Evidence correlation shared by dispatch, detail and persisted status."""

from dataclasses import asdict, dataclass

from backend.metadata.mirrors.types import Authority


def current_open(mirror, operations):
    revision = mirror["control"]["control_revision"]
    published = mirror.get("published_generation_id")
    applied = None
    for op in operations:
        if op["kind"] != "open" or op["control_revision"] != revision:
            continue
        if op["state"] == "pending":
            return op
        if op["state"] == "applied" and published and op.get("publication_receipt", {}).get("generation_id") == published:
            applied = op
    return applied


def registry_scope(mirrors):
    return sorted((dict(mirror_id=mirror["id"], qualified_table=mirror["qualified_table"],
                        table_identity=mirror["table_identity"], mirror_revision=mirror["control"]["control_revision"],
                        included=mirror["enabled"]) for mirror in mirrors),
                  key=lambda entry: (entry["qualified_table"], entry["mirror_id"]))


def current_authority(state, authority, scope):
    expected = asdict(authority)
    expected["binding_id"] = expected.pop("resource_binding_id")
    lineage = expected.pop("capture_generation")
    return (state and state.get("desired") == "configured" and authority.owner_epoch > 0
            and authority.runtime_instance_id and authority.resource_binding_id
            and state.get("capture_generation") is not None and str(state["capture_generation"]) == lineage
            and all(state.get(key) == value for key, value in expected.items())
            and state.get("published_scope") == scope)


def dispatch_scope(desired, state, pending_opens):
    current = state.get("published_scope", [])
    if not current or desired == current or not all(entry in desired for entry in current):
        return desired
    ledger = state.get("incremental_snapshots", {}).get("generations", {})
    if not ledger or state.get("applied_revision") != state.get("control_revision"):
        return desired
    for entry in current:
        if not entry["included"]:
            continue
        for operation in pending_opens.get(entry["mirror_id"], []):
            claim = operation.get("allocation") or {}
            if operation["control_revision"] != entry["mirror_revision"] or not claim.get("observed"):
                continue
            generation = claim["generation_id"]
            scan = ledger.get(generation, {})
            binding = scan.get("binding", {})
            if (scan.get("state") in {"submission_uncertain", "snapshotting", "catching_up", "blocked"}
                    and binding.get("generation_id") == generation and binding.get("mirror_id") == entry["mirror_id"]
                    and binding.get("allocation_operation_id") == operation["id"]
                    and binding.get("authority") == claim["binding"]["authority"]
                    and current_authority(state, Authority(**binding["authority"]), current)):
                return current
    return desired


def _admitted_allocation(mirror, operation, state, scope):
    allocation = operation.get("allocation") if operation else None
    if (not mirror["enabled"] or not allocation or allocation.get("observed") is not True
            or not allocation.get("generation_id") or allocation["mirror_revision"] != mirror["control"]["control_revision"]):
        return None
    if operation["state"] == "applied" and allocation["generation_id"] != mirror["published_generation_id"]:
        return None
    bound = allocation["binding"]
    authority = Authority(**bound["authority"])
    if (not current_authority(state, authority, scope) or state.get("applied_revision") != authority.control_revision
            or not any(entry["mirror_id"] == mirror["id"] and entry["included"]
                       and entry["mirror_revision"] == allocation["mirror_revision"]
                       and entry["table_identity"] == mirror["table_identity"]
                       and entry["qualified_table"] == mirror["qualified_table"] for entry in scope)
            or authority.source_id != mirror["source_id"] or bound["object_id"] != mirror["object_id"]
            or any(bound[key] != mirror[key] for key in ("table_identity", "qualified_table"))):
        return None
    return allocation


def _correlated_snapshot(mirror, pending, allocation, ledger):
    generation, bound = allocation["generation_id"], allocation["binding"]
    snapshot = ledger.get("generations", {}).get(generation, {})
    expected = dict(authority=bound["authority"], mirror_id=mirror["id"], mirror_revision=mirror["control"]["control_revision"],
                    allocation_operation_id=pending["id"], generation_id=generation, table_identity=mirror["table_identity"],
                    qualified_table=mirror["qualified_table"], history_epoch=bound["history_epoch"],
                    schema_fingerprint=bound["schema_fingerprint"], data_partition=bound["partition_identity"])
    if (not snapshot.get("id")
            or any(snapshot.get("binding", {}).get(key) != value for key, value in expected.items())):
        return None
    return snapshot


def _snapshot_stage(snapshot, ledger):
    if not snapshot or snapshot.get("receipt") is not True:
        return None
    if snapshot["state"] == "catching_up" and snapshot.get("scan") and snapshot.get("completion"):
        return "catching_up"
    if (snapshot["state"] == "snapshotting" and ledger.get("active") == snapshot["binding"]["generation_id"]
            and (snapshot.get("scan") or snapshot.get("progress_sample"))):
        return "scan"
    return None


@dataclass(frozen=True)
class OpenEvidence:
    pending: dict | None
    admitted: bool
    snapshot: dict | None
    stage: str | None
    status: str


def open_evidence(mirror, operations, state, scope):
    operation = current_open(mirror, operations)
    pending = operation if operation and operation["state"] == "pending" else None
    allocation = _admitted_allocation(mirror, operation, state, scope)
    ledger = state.get("incremental_snapshots", {})
    snapshot = _correlated_snapshot(mirror, pending, allocation, ledger) if pending and allocation else None
    stage = _snapshot_stage(snapshot, ledger)
    status = mirror["status"]
    if snapshot is not None and snapshot["state"] == "blocked":
        status = "needs_attention"
    elif stage:
        status = "snapshotting" if stage == "scan" else "catching_up"
    elif mirror["enabled"] and not pending and mirror["published_generation_id"] and status in {"waiting", "unknown"}:
        status = "ready"
    return OpenEvidence(pending, allocation is not None, snapshot, stage, status)
