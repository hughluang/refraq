"""Durable PostgreSQL source-channel incremental snapshot orchestration."""

from dataclasses import asdict, dataclass
import math
import re
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from backend.core.time import utc_now
from backend.metadata.capture.authority import SignedAuthority
from backend.metadata.capture.configuration import SnapshotWindow, snapshot_dispatch_allowed
from backend.metadata.capture.control import source_control_transaction
from backend.metadata.capture.runtime_store import RuntimeBlocked
from backend.metadata.capture.store import load_binding, save_binding
from backend.metadata.mirrors.types import Authority, PartitionIdentity


@dataclass(frozen=True)
class SnapshotBinding:
    authority: Authority
    mirror_id: str
    mirror_revision: int
    allocation_operation_id: str
    generation_id: str
    table_identity: str
    qualified_table: str
    history_epoch: str
    schema_fingerprint: str
    data_partition: PartitionIdentity
    connector_name: str
    signal_table: str
    signal_relation_identity: str
    notification_topic: str
    notification_partition: PartitionIdentity

    def validate(self):
        names = (self.qualified_table, self.signal_table)
        if (not all(re.fullmatch(r"[a-z_][a-z0-9_]{0,62}\.[a-z_][a-z0-9_]{0,62}", name) for name in names)
                or self.qualified_table == self.signal_table
                or not all((self.signal_relation_identity, self.connector_name, self.notification_topic,
                            self.data_partition.runtime_cluster_id, self.data_partition.topic_incarnation_id,
                            self.notification_partition.topic_incarnation_id))
                or self.data_partition.runtime_cluster_id != self.notification_partition.runtime_cluster_id
                or self.data_partition == self.notification_partition
                or any(type(identity.partition) is not int or identity.partition != 0
                       for identity in (self.data_partition, self.notification_partition))):
            raise RuntimeBlocked("snapshot_profile_binding_invalid")


@dataclass(frozen=True)
class SnapshotResult:
    operation_id: str | None
    state: str
    scan_offset: int | None = None
    completion_offset: int | None = None


class SnapshotCoordinator:
    """Poll one prepared generation under local exclusion and the management Source lock.

    Recheck must validate the current installed allocation and return the authoritative
    window mode. Signals are bounded deployment adapter calls.
    """

    def __init__(self, *, journal, signals, receipt_trust, notification_trust,
                 max_observation_age_seconds, recheck, dispatch_clock=utc_now):
        receipt_keys = _signing_keys(receipt_trust)
        notification_keys = _signing_keys(notification_trust)
        if not receipt_keys or not notification_keys or receipt_keys & notification_keys:
            raise RuntimeBlocked("snapshot_independent_observers_required")
        if (type(max_observation_age_seconds) not in {int, float}
                or not math.isfinite(max_observation_age_seconds) or max_observation_age_seconds <= 0):
            raise RuntimeBlocked("snapshot_observation_budget_required")
        self.journal = journal
        self.signals = signals
        self.receipt_trust = SignedAuthority(keys=receipt_trust.keys, issuer=receipt_trust.issuer,
                                            audience=receipt_trust.audience)
        self.notification_trust = SignedAuthority(keys=notification_trust.keys, issuer=notification_trust.issuer,
                                                 audience=notification_trust.audience)
        self.max_observation_age_seconds = max_observation_age_seconds
        self.recheck = recheck
        self.dispatch_clock = dispatch_clock

    def reconcile(self, binding: SnapshotBinding) -> SnapshotResult:
        binding.validate()
        source_id = binding.authority.source_id
        with self.journal.source_lock(source_id):
            with source_control_transaction(source_id) as (session, source):
                state, mode = self._current(binding, session, source)
                ledger = state.setdefault("incremental_snapshots", {"active": None, "generations": {}})
                operation = ledger["generations"].get(binding.generation_id)
                if operation is not None:
                    if operation["binding"] != asdict(binding):
                        raise RuntimeBlocked("snapshot_binding_conflict")
                    if operation["state"] not in {"awaiting_dispatch", "waiting_window"}:
                        return self._observe(session, state, binding, operation)
                if ledger["active"] not in (None, binding.generation_id):
                    return SnapshotResult(None, "source_busy")
                if not self._window_open(source, mode):
                    return SnapshotResult(operation["id"] if operation else None, "waiting_window")
                if operation is None:
                    operation = {"id": str(uuid4()), "binding": asdict(binding)}
                    ledger["generations"][binding.generation_id] = operation
                operation_id = operation["id"]
                challenge = uuid4().hex
                baseline = self.signals.baseline(binding, operation_id, challenge=challenge)
                if baseline is None:
                    raise RuntimeBlocked("snapshot_baseline_unavailable")
                evidence = self._evidence(self.notification_trust, baseline, "baseline", binding, operation_id,
                                          challenge=challenge)
                if (evidence.get("idle") is not True or evidence.get("exclusive") is not True
                        or type(evidence.get("offset")) is not int or evidence["offset"] < 0):
                    raise RuntimeBlocked("snapshot_baseline_unconfirmed")
                operation.update(state="submission_uncertain", cursor=evidence["offset"])
                reserved = dict(operation)
                ledger["active"] = binding.generation_id
                save_binding(session, state)

            with source_control_transaction(source_id) as (session, source):
                state, mode = self._current(binding, session, source)
                ledger = state["incremental_snapshots"]
                operation = ledger["generations"].get(binding.generation_id)
                if ledger["active"] != binding.generation_id or operation != reserved:
                    if (ledger["active"] == binding.generation_id and operation is not None
                            and operation["id"] == operation_id
                            and operation["state"] in {"submission_uncertain", "snapshotting"}):
                        operation.update(state="blocked", fault="snapshot_dispatch_claim_changed")
                        save_binding(session, state)
                    return SnapshotResult(operation_id, "blocked")
                dispatch_error = None
                try:
                    self._evidence(self.notification_trust, baseline, "baseline", binding, operation_id,
                                   challenge=challenge)
                except RuntimeBlocked as error:
                    dispatch_error = error
                if dispatch_error is None and self._window_open(source, mode):
                    try:
                        self.signals.submit(binding, self._signal(binding, operation_id))
                    except TimeoutError:
                        pass
                    return SnapshotResult(operation_id, "submission_uncertain")
                operation["state"] = "awaiting_dispatch" if dispatch_error is not None else "waiting_window"
                del operation["cursor"]
                ledger["active"] = None
                save_binding(session, state)
            if dispatch_error is not None:
                raise dispatch_error
            return SnapshotResult(operation_id, "waiting_window")

    def _observe(self, session, state, binding, operation):
        operation_id = operation["id"]
        if operation["state"] in {"submission_uncertain", "snapshotting"}:
            if not operation.get("receipt"):
                token = self.signals.receipt(binding, operation_id)
                if token is not None:
                    receipt = self._evidence(self.receipt_trust, token, "receipt", binding, operation_id)
                    if receipt == self._signal(binding, operation_id):
                        operation.update(receipt=True, state="snapshotting")
                    else:
                        operation.update(state="blocked", fault="snapshot_receipt_conflict")
            current_observation = False
            if operation["state"] != "blocked":
                challenge = uuid4().hex
                token = self.signals.notifications(binding, operation_id, operation["cursor"], challenge=challenge)
                if token is not None:
                    batch = self._evidence(self.notification_trust, token, "notifications", binding, operation_id,
                                           challenge=challenge)
                    current_observation = self._notifications(binding, operation, batch)
            if (current_observation and operation.get("receipt")
                    and "scan" in operation and "completion" in operation):
                operation["state"] = "catching_up"
                state["incremental_snapshots"]["active"] = None
            save_binding(session, state)
        if operation["state"] == "catching_up":
            return SnapshotResult(operation_id, "catching_up", operation["scan"]["offset"],
                                  operation["completion"]["offset"])
        return SnapshotResult(operation_id, operation["state"])

    @staticmethod
    def _notifications(binding, operation, batch):
        start, end, records = batch.get("start"), batch.get("end"), batch.get("records")
        high_water = batch.get("high_water")
        cursor = operation["cursor"]
        if (batch.get("exclusive") is not True or type(start) is not int or start < 0
                or type(end) is not int or not isinstance(records, list) or end != start + len(records)
                or type(high_water) is not int or high_water < max(end, operation.get("notification_high_water", cursor))):
            operation.update(state="blocked", fault="snapshot_notification_range_unconfirmed")
            return False
        if start < cursor and end <= cursor:
            operation["notification_high_water"] = high_water
            return False
        if start != cursor:
            operation.update(state="blocked", fault="snapshot_notification_range_unconfirmed")
            return False
        for offset, record in enumerate(records, start=start):
            if not _record_notification(binding, operation, record, offset):
                operation.update(state="blocked", fault="snapshot_notification_conflict")
                return False
        operation["cursor"] = end
        operation["notification_high_water"] = high_water
        return end == high_water

    def _current(self, binding, session, source):
        state = load_binding(session, source.id)
        stamps = asdict(binding.authority)
        stamps["binding_id"] = stamps.pop("resource_binding_id")
        lineage = stamps.pop("capture_generation")
        target = {key: getattr(binding, key) for key in (
            "mirror_id", "mirror_revision", "table_identity", "qualified_table",
        )}
        if (state is None or any(state.get(key) != value for key, value in stamps.items())
                or str(state.get("capture_generation")) != lineage or state.get("desired") != "configured"
                or state.get("applied_revision") != binding.authority.control_revision
                or binding.authority.owner_epoch < 1 or not binding.authority.runtime_instance_id
                or source.status != "active" or source.engine != "postgresql"
                or not source.capture_credential_ciphertext
                or source.capture_revision != binding.authority.credential_revision
                or not any(entry["included"] is True and all(entry.get(key) == value for key, value in target.items())
                           for entry in state["published_scope"])):
            raise RuntimeBlocked("snapshot_current_authority_required")
        mode = self.recheck(binding, session=session, source=source)
        if mode not in ("window", "run_now"):
            raise RuntimeBlocked("snapshot_dispatch_not_authorized")
        return state, mode

    def _evidence(self, trust, token, purpose, binding, operation_id, *, challenge=None):
        claims = trust.verify(token, purpose=f"snapshot:{purpose}", authority=asdict(binding.authority),
                              scope=asdict(binding), operation_id=operation_id)
        if challenge is not None and claims.get("challenge") != challenge:
            raise RuntimeBlocked("snapshot_notification_observation_replayed")
        evidence = claims.get("evidence")
        if (not isinstance(evidence, dict)
                or utc_now().timestamp() - claims["iat"] > self.max_observation_age_seconds):
            raise RuntimeBlocked("snapshot_evidence_stale_or_invalid")
        return evidence

    def _window_open(self, source, mode):
        window = SnapshotWindow.model_validate(source.snapshot_window) if source.snapshot_window is not None else None
        return mode == "run_now" or snapshot_dispatch_allowed(window, self.dispatch_clock())

    @staticmethod
    def _signal(binding, operation_id):
        return {"id": operation_id, "type": "execute-snapshot",
                "data": {"type": "incremental", "data-collections": [re.escape(binding.qualified_table)]}}


def _signing_keys(trust):
    if not isinstance(trust, SignedAuthority) or not all(isinstance(key, Ed25519PublicKey) for key in trust.keys.values()):
        return set()
    return {key.public_bytes_raw() for key in trust.keys.values()}


def _decimal(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,19}", value):
        return int(value)
    return None


def _record_notification(binding, operation, record, offset):
    if (not isinstance(record, dict) or type(record.get("offset")) is not int or record["offset"] != offset
            or not isinstance(record.get("value"), dict)):
        return False
    value = record["value"]
    data = value.get("additional_data")
    timestamp = _decimal(value.get("timestamp"))
    if not isinstance(data, dict) or data.get("connector_name") != binding.connector_name or not timestamp:
        return False
    kind, aggregate = value.get("type"), value.get("aggregate_type")
    if aggregate == "Initial Snapshot" and kind == "SKIPPED":
        if "scan" in operation:
            return False
        operation.pop("notification_phase", None)
        operation.pop("notification_timestamp", None)
        operation.pop("progress_sample", None)
        operation.pop("byte_sample", None)
        return True
    if (aggregate != "Incremental Snapshot" or value.get("id") != operation["id"]
            or record.get("key") != {"id": operation["id"]} or "completion" in operation):
        return False
    phase = operation.get("notification_phase")
    if timestamp < operation.get("notification_timestamp", 0):
        return False
    if kind == "STARTED" and phase is None:
        if data.get("data_collections") != binding.qualified_table:
            return False
    elif kind == "DATA_COLLECTIONS_RESOLVED" and phase == "STARTED":
        if data.get("data_collections") != binding.qualified_table:
            return False
    elif kind == "IN_PROGRESS" and phase in {"DATA_COLLECTIONS_RESOLVED", "IN_PROGRESS"}:
        if data.get("current_collection_in_progress") != binding.qualified_table:
            return False
    elif kind == "TABLE_SCAN_COMPLETED" and phase in {"DATA_COLLECTIONS_RESOLVED", "IN_PROGRESS"}:
        status, rows = data.get("status"), _decimal(data.get("total_rows_scanned"))
        if ("scan" in operation or data.get("scanned_collection") != binding.qualified_table
                or not ((status == "EMPTY" and rows == 0) or (status == "SUCCEEDED" and rows is not None and rows > 0))):
            return False
        operation["scan"] = dict(offset=offset, timestamp=timestamp, status=status, rows=rows)
    elif kind == "COMPLETED" and phase == "TABLE_SCAN_COMPLETED":
        operation["completion"] = dict(offset=offset, timestamp=timestamp)
    else:
        return False
    if kind in {"STARTED", "DATA_COLLECTIONS_RESOLVED", "IN_PROGRESS", "TABLE_SCAN_COMPLETED"}:
        # Native Debezium notifications have no byte counter. A deployment
        # observer may attach measured bytes to the signed, table-bound sample.
        previous = operation.get("byte_sample")
        if previous is None:
            legacy = operation.get("progress_sample", {})
            if "scanned_bytes" in legacy:
                # Earlier ledgers carried bytes forward under a later notification's timestamp.
                previous = {key: legacy[key] for key in ("scanned_bytes", "scan_total_bytes") if key in legacy}
                operation["byte_sample"] = previous
        operation["progress_sample"] = dict(offset=offset, timestamp=timestamp)
        measured = _decimal(data.get("scanned_bytes"))
        if measured is not None and (previous is None or measured >= previous["scanned_bytes"]):
            sample = dict(scanned_bytes=measured, offset=offset, timestamp=timestamp)
            total = _decimal(data.get("scan_total_bytes"))
            if "scan_total_bytes" not in data and previous is not None:
                total = previous.get("scan_total_bytes")
            if total and measured <= total:
                sample["scan_total_bytes"] = total
            operation["byte_sample"] = sample
    operation.update(notification_phase=kind, notification_timestamp=timestamp)
    return True
