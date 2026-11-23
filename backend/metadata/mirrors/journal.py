"""Operator requests and runtime observations attached to their durable operations."""

from datetime import UTC, datetime
from hashlib import sha256

from backend.metadata.mirrors.errors import MirrorError


def observation(operation, kind, *, at, reference, epoch=None, generation=None):
    identity = sha256(f"{operation['id']}:{kind}:{reference}".encode()).hexdigest()
    events = operation.setdefault("observations", [])
    if any(event["id"] == identity for event in events):
        return False
    events.append(dict(id=identity, category="observation", kind=kind, at=at, operation_id=operation["id"],
                       control_revision=operation["control_revision"], history_epoch=epoch, generation_id=generation,
                       outcome=None, outcome_at=None, related_operation_id=None))
    return True


def result(operation, outcome, at, related=None):
    operation.update(result=dict(outcome=outcome, outcome_at=at, related_operation_id=related))


def project_stop_receipt(mirror, operation):
    """Attach an exact durable stop, including confirmations recorded before journal events."""
    control = mirror["control"]
    ack = control.get("stop_ack")
    if (not ack or mirror["enabled"] or mirror["status"] != "disabled"
            or operation["kind"] != "disable" or operation["state"] != "applied"
            or operation["id"] != ack["operation_id"] or operation["mirror_id"] != mirror["id"]
            or operation["control_revision"] != control["control_revision"]
            or operation["control_revision"] != control["applied_revision"]
            or not ack["observed_at"] or ack["observed_at"] != control["observed_at"]
            or ack["source_operation_id"] not in operation["observed_evidence_refs"]):
        return False
    added = observation(operation, "stop_confirmed", at=ack["observed_at"], reference=ack["source_operation_id"],
                        epoch=mirror.get("history_epoch"), generation=mirror["published_generation_id"])
    result(operation, "stop_confirmed", ack["observed_at"])
    return added


def requests_at_revision(operations, revision):
    return [op for op in operations if op["control_revision"] == revision and
            (op["kind"] in {"disable", "retry"} or (op["kind"] == "open" and op.get("operator_intent")))]


def recheck_request(operations, mirror):
    requests = requests_at_revision(operations, mirror["control"]["control_revision"])
    pending = [op for op in requests if op["kind"] == "retry" and op["state"] == "pending"]
    if pending:
        return pending[0]
    if mirror.get("blocker"):
        retries = [op for op in requests if op["kind"] == "retry" and op["state"] == "applied"]
        if retries:
            return max(retries, key=lambda op: (op["requested_at"], op["id"]))
    opens = [op for op in requests if op["kind"] == "open"]
    return opens[0] if opens else None


def note_check(store, session, mirror, operation_id, kind, *, at, reference, epoch=None, generation=None, historical=False):
    operations = store.ops(session, mirror["id"])
    requests = requests_at_revision(operations, mirror["control"]["control_revision"])
    operation = next((op for op in requests if op["id"] == operation_id), None)
    if operation is None or not mirror["enabled"]:
        return False
    if not observation(operation, kind, at=at, reference=reference, epoch=epoch, generation=generation):
        return False
    blocker = mirror.get("blocker")
    cause = kind.split("_")[0]
    blocked = kind in {"continuity_unknown", "schema_blocked", "permission_blocked"}
    if operation["kind"] == "retry" and operation["state"] == "pending":
        operation["state"] = "applied"
        result(operation, kind, at)
    store.save_op(session, operation)
    if historical or operation.get("result", {}).get("outcome") == "resolved_by_evidence":
        return True
    if blocker and datetime.fromisoformat(at) < datetime.fromisoformat(blocker["last_checked_at"]) and blocked:
        return True
    if blocked:
        mirror["blocker"] = dict(cause=cause, since=blocker["since"] if blocker and blocker["cause"] == cause else at,
                                 last_checked_at=at)
    elif blocker and blocker["cause"] == cause:
        mirror["blocker"] = None
        for other in requests:
            if other["id"] != operation_id and other["kind"] == "retry" and other["state"] == "pending":
                other["state"] = "applied"
                result(other, "resolved_by_evidence", at, operation_id)
                store.save_op(session, other)
    store.save(session, mirror)
    return True


def _snapshot_events(operation, scan):
    binding = scan["binding"]
    events = []

    def append(kind, instant):
        temp = dict(operation, observations=[])
        observation(temp, kind, at=instant, reference=f"{scan['id']}:{kind}",
                    epoch=operation.get("requested_epoch"), generation=binding["generation_id"])
        events.extend(temp["observations"])

    if scan.get("receipt"):
        for kind, record in (("scan", scan.get("scan")), ("catching_up", scan.get("completion"))):
            if record and type(record.get("timestamp")) is int and 0 <= record["timestamp"] < 253402300800000:
                append(kind, datetime.fromtimestamp(record["timestamp"] / 1000, UTC).isoformat())
    if scan.get("released_at"):
        append("slot_released", scan["released_at"])
    return events


def timeline(operations, ledger, mirror):
    by_id = {op["id"]: op for op in operations}
    by_revision = {}
    events = []
    for op in operations:
        project_stop_receipt(mirror, op)
        by_revision.setdefault(op["control_revision"], []).append(op)
        events.extend(op.get("observations", []))
    for scan in ledger.get("generations", {}).values():
        binding = scan.get("binding", {})
        operation = by_id.get(binding.get("allocation_operation_id"))
        if operation and scan.get("id") and binding.get("mirror_id") == operation["mirror_id"]:
            events.extend(_snapshot_events(operation, scan))
    for revision, attempts in by_revision.items():
        for op in requests_at_revision(attempts, revision):
            kind = op["kind"]
            if kind == "open" and revision > 1:
                kind = "resume"
            effective = op
            if op["kind"] == "open":
                opens = [item for item in attempts if item["kind"] == "open" and item["state"] != "superseded"]
                if len(opens) == 1:
                    effective = opens[0]
                elif op["state"] == "superseded":
                    attempts_with_result = [item for item in attempts if item["kind"] == "open" and item.get("result")]
                    if attempts_with_result:
                        effective = max(attempts_with_result, key=lambda item: item["requested_at"])
            outcome = effective.get("result")
            if outcome and effective["id"] != op["id"] and not outcome["related_operation_id"]:
                outcome = dict(outcome, related_operation_id=effective["id"])
            if not outcome:
                if effective["state"] != "pending":
                    label = effective["state"]
                elif kind == "disable":
                    label = "awaiting_stop"
                elif kind == "retry":
                    label = "awaiting_recheck"
                elif op.get("requested_generation") and not effective.get("reopen_baseline"):
                    label = "awaiting_continuity"
                else:
                    label = "awaiting_publication"
                outcome = dict(outcome=label, outcome_at=None, related_operation_id=None)
            events.append(dict(id=op["id"], category="request", kind=kind, at=op["requested_at"],
                               operation_id=op["id"], control_revision=revision, history_epoch=op.get("requested_epoch"),
                               generation_id=op.get("requested_generation"), **outcome))
    return sorted(events, key=lambda event: (datetime.fromisoformat(event["at"]), event["id"]), reverse=True)


def page(events, before, limit):
    start = 0
    if before:
        match = next((index for index, event in enumerate(events) if event["id"] == before), None)
        if match is None:
            raise MirrorError("REQUEST_INVALID", 422)
        start = match + 1
    items = events[start:start + limit]
    return dict(items=items, next_cursor=items[-1]["id"] if start + limit < len(events) else None)
