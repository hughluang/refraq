"""Protected delivery installation and independent lease admission."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import time
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.core.db import get_session_factory
from backend.metadata.capture.control import (
    AUTHORITY_KEYS, selected_tables, source_control_transaction,
)
from backend.metadata.capture.decoder import PostgreSQLDecoder
from backend.metadata.capture.delivery import DeliveryBinding, DeliveryLimits, open_delivery
from backend.metadata.capture.postgresql import TablePrerequisiteFailed
from backend.metadata.capture.runtime_store import RuntimeBlocked, protected_json, protected_read
from backend.metadata.capture.snapshot import SnapshotBinding
from backend.metadata.capture.store import load_binding
from backend.metadata.mirrors.bootstrap import validate_target
from backend.metadata.mirrors.history import History, SqlHistoryTarget
from backend.metadata.mirrors.publication import Publication
from backend.metadata.mirrors.errors import MirrorError
from backend.metadata.mirrors.reconciliation import (
    OpenGenerationBinding, confirm_retained_opens, current_open_preparations, initial_history_epoch,
    reconcile_open_generation, request_reopen_baseline, require_current_open_allocations,
    require_current_retained_opens, lifecycle_checks, record_continuity_receipt, table_prerequisite_check,
)
from backend.metadata.mirrors.service import read_dispatch_scope
from backend.metadata.mirrors.types import AnchoredProfile, Authority, PartitionIdentity


FACTS = {"owner_excluded", "target_fenced", "source_pressure", "alarm_drill",
         "credential_valid", "installed_schema_key", "topic_recreation_excluded",
         "nontransactional_producer", "uncompacted_topic", "sole_partition",
         "broker_message_bounds", "process_memory_bounded", "profile_qualified",
         "exclusion_held_until_release"}


def applier_engine(settings):
    """No arbitrary driver options, role switching, or inherited URL parameters."""
    url = make_url(protected_read(settings["url_file"]).decode().strip())
    timeout = settings["timeout_seconds"]
    if (url.drivername != "postgresql+psycopg" or url.username != "refraq_mirror_applier"
            or not url.host or not url.database or not url.password
            or set(url.query) != {"sslmode", "sslrootcert"}
            or url.query["sslmode"] != "verify-full"
            or type(timeout) is not int or not 1 <= timeout <= 30):
        raise RuntimeBlocked("restricted_applier_profile_required")
    protected_read(url.query["sslrootcert"])
    return create_engine(
        url, hide_parameters=True, echo=False, pool_size=1, max_overflow=0,
        pool_timeout=timeout, pool_pre_ping=False,
        connect_args={"connect_timeout": timeout,
                      "options": f"-c statement_timeout={timeout * 1000} -c lock_timeout={timeout * 1000}"},
    )


def target_metadata(engine, generation_id):
    with engine.connect() as connection:
        validate_target(connection.connection.driver_connection, expected_role="refraq_mirror_applier")
        return connection.execute(text(
            "SELECT source_mirror_state.delivery_metadata(:generation)"
        ), {"generation": generation_id}).scalar_one()


def _target_authority(command):
    authority = {key: command[key] for key in AUTHORITY_KEYS}
    authority["resource_binding_id"] = authority.pop("binding_id")
    authority["capture_generation"] = str(authority["capture_generation"])
    return authority


def _manifest_anchor(table):
    raw = table.get("anchored_profile")
    if "anchored_profile" not in table:
        return None
    if (not isinstance(raw, dict) or set(raw) != {"kind", "leader_epoch"}
            or type(raw["leader_epoch"]) is not int or raw["leader_epoch"] < 0
            or raw["kind"] != "disposable_read_committed_v1"
            or type(table.get("start_offset")) is not int or table["start_offset"] < -1):
        raise RuntimeBlocked("delivery_anchored_profile_invalid")
    return AnchoredProfile(raw["leader_epoch"])


@dataclass(frozen=True)
class RetainedOpenCandidate:
    mirror_id: str
    operation_id: str
    generation_id: str
    binding: OpenGenerationBinding
    topic: str
    certificate_ref: str
    source_checkpoint: dict
    target_seek_offset: int


def _confirmed_checkpoint(evidence, scope, *, data_topics, data_partitions):
    checkpoint = evidence.get("durable_source_checkpoint")
    exclusion = evidence.get("producer_exclusion")
    if not isinstance(checkpoint, dict) or not isinstance(exclusion, dict):
        raise RuntimeBlocked("published_open_checkpoint_unconfirmed")
    topic = checkpoint.get("topic")
    partition = checkpoint.get("partition")
    notification = evidence["source_completion"]
    lineage = exclusion.get("source_lineage")
    if (not isinstance(topic, str) or not topic or topic in data_topics or topic == notification["notification_topic"]
            or not isinstance(partition, dict) or set(partition) != {"runtime_cluster_id", "topic_incarnation_id", "partition"}
            or not isinstance(partition["topic_incarnation_id"], str) or not partition["topic_incarnation_id"]
            or type(partition["partition"]) is not int or partition["partition"] != 0
            or any(partition["runtime_cluster_id"] != data.runtime_cluster_id
                   or partition["topic_incarnation_id"] == data.topic_incarnation_id for data in data_partitions)
            or partition["topic_incarnation_id"] == notification["notification_partition"]["topic_incarnation_id"]
            or checkpoint.get("key") != [scope["connector_name"], {"server": scope["topic_prefix"]}]
            or exclusion.get("slot") != scope["slot"] or exclusion.get("publication") != scope["publication"]
            or not isinstance(lineage, list) or len(lineage) != 4
            or any(not isinstance(value, str) or not value for value in lineage)):
        raise RuntimeBlocked("published_open_checkpoint_unconfirmed")
    value = checkpoint.get("value")
    witness = checkpoint.get("wal_witness")
    if (not isinstance(value, dict) or not isinstance(witness, dict) or value.get("messageType") != "COMMIT"
            or any(type(value.get(key)) is not int for key in ("txId", "lsn", "lsn_proc", "lsn_commit"))
            or any(type(witness.get(key)) is not int
                   for key in ("xid", "wal_start", "wal_end", "commit_lsn", "previous_checkpoint_offset"))
            or any(type(checkpoint.get(key)) is not int for key in ("offset", "eof"))
            or type(exclusion.get("confirmed_flush_lsn")) is not int
            or not 0 <= witness["previous_checkpoint_offset"] < checkpoint["offset"] < checkpoint["eof"]
            or not 0 < witness["xid"] == value["txId"]
            or not 0 < witness["wal_start"] < witness["wal_end"] <= exclusion["confirmed_flush_lsn"]
            or not witness["wal_start"] <= witness["commit_lsn"] <= witness["wal_end"]
            or not witness["commit_lsn"] == value["lsn"] == value["lsn_proc"] == value["lsn_commit"]):
        raise RuntimeBlocked("published_open_checkpoint_unconfirmed")
    return checkpoint


def _canonical_coverage(coverage, *, authority, leader_epoch, earliest, end, sealed):
    fields = {"authority", "start", "end", "before", "after", "offsets"}
    if sealed:
        fields.add("eof")
    if not isinstance(coverage, dict) or set(coverage) != fields:
        return False
    start, offsets = coverage["start"], coverage["offsets"]
    if (coverage["authority"] != authority
            or any(type(coverage["authority"][key]) is not type(value) for key, value in authority.items())
            or type(start) is not int or not earliest <= start <= end
            or type(coverage["end"]) is not int or coverage["end"] != end
            or not isinstance(offsets, list)
            or any(type(offset) is not int or not start <= offset < end for offset in offsets)
            or any(left >= right for left, right in zip(offsets, offsets[1:]))):
        return False
    stable = high = end
    for name in ("before", "after"):
        bounds = coverage[name]
        if (not isinstance(bounds, dict) or set(bounds) != {"low", "stable", "high", "leader_epoch"}
                or any(type(value) is not int for value in bounds.values())
                or bounds["low"] != 0 or bounds["leader_epoch"] != leader_epoch
                or not stable <= bounds["stable"] <= bounds["high"] <= 2**63 - 1
                or bounds["high"] < high):
            return False
        stable, high = bounds["stable"], bounds["high"]
    if sealed:
        return type(coverage["eof"]) is int and coverage["eof"] == stable == high == end
    return bool(offsets) and offsets[-1] == end - 1


def _retained_coverage(metadata, seal, publisher, leader_epoch, seek):
    coverage = metadata.get("anchored_coverage")
    if seek == seal["eof"]:
        return (coverage == seal and _canonical_coverage(coverage, authority=publisher, leader_epoch=leader_epoch,
                                                        earliest=seal["start"], end=seek, sealed=True))
    if not isinstance(coverage, dict):
        return False
    authority = coverage.get("authority")
    if not isinstance(authority, dict) or (authority != publisher and metadata.get("anchored_coverage_authorized") is not True):
        return False
    return _canonical_coverage(coverage, authority=authority, leader_epoch=leader_epoch,
                               earliest=seal["eof"], end=seek, sealed=False)


class SourceDelivery:
    """A protected immutable manifest; changes require process configuration reload."""

    def __init__(self, *, settings_file, source_id, journal, signals, verifier, profile):
        self.settings_file = settings_file
        self.source_id = source_id
        self.journal, self.signals, self.verifier = journal, signals, verifier
        self.profile = profile
        self.engine = None
        self.clients = []
        self.stamp = None
        self.prepared_command = None
        self.retained = {}
        self.resume_operation_id = None
        self.admitted_generations = set()
        self.client_generations = set()

    def _load_installation(self):
        if self.engine is not None:
            return
        try:
            settings = protected_json(self.settings_file)
            if set(settings) != {"target", "tables", "kafka", "group_id", "limits", "max_age_seconds"}:
                raise RuntimeBlocked("delivery_settings_invalid")
            limits = DeliveryLimits(**settings["limits"])
            limits.validate()
            max_age = settings["max_age_seconds"]
            if type(max_age) is not int or not 1 <= max_age <= 60:
                raise RuntimeBlocked("delivery_freshness_required")
            tables = settings["tables"]
            if not isinstance(tables, list) or not 1 <= len(tables) <= 100:
                raise RuntimeBlocked("delivery_tables_invalid")
            engine = applier_engine(settings["target"])
        except RuntimeBlocked:
            raise
        except Exception:
            raise RuntimeBlocked("delivery_installation_unconfirmed") from None
        self.settings, self.limits, self.max_age, self.manifest_tables = settings, limits, max_age, tables
        self.tables = tables
        self.engine = engine
        self.history = None
        if self.profile.snapshot is not None:
            self.history = History(session_factory=get_session_factory(), target=SqlHistoryTarget(
                engine=engine, invalidation_engine=engine, timeout_ms=settings["target"]["timeout_seconds"] * 1000,
            ))

    def _current(self, session, source):
        state = load_binding(session, self.source_id)
        if (state is None or source.status != "active" or not source.capture_credential_ciphertext
                or source.capture_revision != state["credential_revision"]
                or state["desired"] != "configured" or state["owner_epoch"] <= 0
                or state["runtime_instance_id"] != self.signals.runtime_instance_id):
            raise RuntimeBlocked("delivery_current_authority_required")
        scope = read_dispatch_scope(session, self.source_id, state=state)
        if scope != state.get("published_scope"):
            raise RuntimeBlocked("published_scope_changed")
        self._load_installation()
        self._validate_manifest(scope)
        self._require_current_allocations(session, state)
        return {key: state[key] for key in AUTHORITY_KEYS}

    def _validate_manifest(self, scope):
        expected = {entry["qualified_table"]: entry["table_identity"]
                    for entry in selected_tables(self.profile.scope, scope)}
        try:
            inventory = {f'{table["decoder"]["schema_name"]}.{table["decoder"]["table_name"]}': table
                         for table in self.manifest_tables}
        except (KeyError, TypeError):
            raise RuntimeBlocked("delivery_manifest_scope_mismatch") from None
        if (not expected or inventory.keys() != set(self.profile.scope["tables"])
                or len(inventory) != len(self.manifest_tables)
                or any(inventory[name]["decoder"]["table_identity"] != identity for name, identity in expected.items())):
            raise RuntimeBlocked("delivery_manifest_scope_mismatch")
        selected = [inventory[name] for name in expected]
        if getattr(self.profile, "snapshot", None) is not None:
            for table in selected:
                binding = table["partition_identity"]
                notification = self.profile.snapshot["notification_partition"]
                if (table["decoder"]["connector_version"] != "3.7.1.Final"
                        or binding["runtime_cluster_id"] != notification["runtime_cluster_id"]
                        or binding["topic_incarnation_id"] == notification["topic_incarnation_id"]):
                    raise RuntimeBlocked("delivery_snapshot_profile_mismatch")
        return selected

    def prepare(self, command) -> tuple[RetainedOpenCandidate, ...]:
        """Prepare ordinary tables or recover the observed Source's sealed candidates."""
        self._load_installation()
        scope = command["published_scope"]
        tables = self._validate_manifest(scope)
        authority = Authority(**_target_authority(command))
        if authority.source_id != self.source_id or authority.runtime_instance_id != self.signals.runtime_instance_id:
            raise RuntimeBlocked("delivery_current_authority_required")
        topics = {table["topic"] for table in tables}
        partitions = tuple(PartitionIdentity(**table["partition_identity"]) for table in tables)
        installed, retained = [], {}
        failures = []
        checks = lifecycle_checks(command["source_id"], scope)
        for table in tables:
            entry = next(item for item in scope if item["included"] and item["table_identity"] == table["decoder"]["table_identity"])
            check_id = checks.get(entry["mirror_id"])
            try:
                identity = table["decoder"]["table_identity"]
                pending, applied = current_open_preparations(
                    authority=authority, published_scope=scope, observe_committed=self._observe_committed,
                    selected_table_ids={identity}, history=self.history,
                )
                if applied:
                    opened, = applied
                    evidence = opened.observed.certificate["evidence"]
                    checkpoint = _confirmed_checkpoint(evidence, self.profile.scope, data_topics=topics, data_partitions=partitions)
                    table = dict(table, start_offset=opened.binding.start_offset)
                    candidate = self._resume_candidate(table, opened, checkpoint)
                    entry = next(entry for entry in scope if entry["mirror_id"] == opened.mirror_id)
                    prepared = dict(table, authority=asdict(authority), generation_id=candidate.generation_id,
                                    decoder={**table["decoder"], "capture_generation": authority.capture_generation},
                                    open=dict(entry, operation_id=opened.operation_id, history_epoch=opened.binding.history_epoch),
                                    fence_receipt=opened.observed.allocation["fence_receipt"])
                    retained[candidate.generation_id] = (candidate, evidence, prepared)
                else:
                    opened = pending[0] if pending else None
                    cached = next((row for row in self.tables if row["decoder"]["table_identity"] == identity
                                   and row.get("open") == opened), None)
                    prepared = (cached if self.prepared_command == command and cached is not None
                                else self._prepare_table(command, authority, table, opened))
                installed.append(prepared)
                if check_id:
                    table_prerequisite_check(command, table=entry["qualified_table"], cause="schema", passed=True,
                                             request_id=check_id)
            except TablePrerequisiteFailed as failure:
                if check_id:
                    table_prerequisite_check(command, table=entry["qualified_table"], cause="schema", passed=False,
                                             request_id=check_id)
                failures.append(failure)
            except (MirrorError, KeyError, TypeError, ValueError):
                failures.append(RuntimeBlocked("open_generation_preparation_blocked"))
            except RuntimeBlocked as failure:
                failures.append(failure)
        if not installed:
            self.prepared_command = None
            raise failures[0]
        if self.resume_operation_id is not None and (not retained or self.prepared_command != command):
            self.retire()
            self.resume_operation_id = None
            self.admitted_generations.clear()
        self.tables = installed
        self.retained = retained
        self.prepared_command = command
        return tuple(value[0] for value in retained.values())

    def resume_retained(self, command, candidates):
        generation_ids = {item.generation_id for item in candidates}
        if (self.prepared_command != command or not candidates
                or generation_ids != self.retained.keys() or len(generation_ids) != len(candidates)
                or any(self.retained[item.generation_id][0] != item for item in candidates)):
            raise RuntimeBlocked("retained_position_resume_inventory_changed")
        for generation_id in generation_ids:
            _, _, table = self.retained[generation_id]
            if _manifest_anchor(table) is None:
                raise RuntimeBlocked("delivery_anchored_profile_mismatch")
        authority = {key: command[key] for key in AUTHORITY_KEYS}
        serialized = [asdict(item) for item in sorted(candidates, key=lambda item: item.mirror_id)]
        scope = json.loads(json.dumps(dict(profile=self.profile.scope, published_scope=command["published_scope"],
                                           candidates=serialized)))
        identity = dict(authority=authority, **scope)
        identity["candidates"] = [{key: value for key, value in item.items() if key != "target_seek_offset"}
                                  for item in scope["candidates"]]
        checks = lifecycle_checks(command["source_id"], command["published_scope"])
        if checks:
            identity["lifecycle_checks"] = checks
        operation_id = sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        decisions = self.signals.resume_retained(command, dict(operation_id=operation_id, authority=authority, scope=scope))
        current = Authority(**_target_authority(command))
        admitted = []
        for item in candidates:
            if not decisions and item.binding.authority == current:
                admitted.append(item)
                continue
            decision = (decisions or {}).get(item.mirror_id)
            if not decision:
                raise RuntimeBlocked("retained_position_resume_unconfirmed")
            check = checks.get(item.mirror_id)
            consumed = check and record_continuity_receipt(
                authority=current, scope=command["published_scope"], mirror_id=item.mirror_id,
                check_id=check, decision=decision, published_operation_id=item.operation_id,
            )
            if consumed:
                if consumed == "retained":
                    admitted.append(item)
                continue
            if decision["result"] == "gap":
                entry = next(entry for entry in command["published_scope"] if entry["mirror_id"] == item.mirror_id)
                request_reopen_baseline(authority=current, published_scope=command["published_scope"],
                                        mirror_id=item.mirror_id, mirror_revision=entry["mirror_revision"],
                                        operation_id=item.operation_id, evidence_ref=decision["evidence_ref"],
                                        partition_identity=decision["partition_identity"], start_offset=decision["start_offset"],
                                        history=self.history, check_id=checks.get(item.mirror_id),
                                        observed_at=decision.get("observed_at"))
            elif decision["result"] == "continuous":
                admitted.append(item)
        if admitted:
            confirm_retained_opens(authority=current, published_scope=command["published_scope"], candidates=admitted,
                                   decisions=decisions, checks=checks)
        approved_ids = {item.generation_id for item in admitted}
        if operation_id != self.resume_operation_id or approved_ids != self.admitted_generations:
            self.retire()
        self.admitted_generations = approved_ids
        self.resume_operation_id = operation_id
        fresh = [table for table in self.tables if table["generation_id"] not in generation_ids]
        self.retained = {key: value for key, value in self.retained.items() if key in approved_ids}
        self.tables = fresh + [self.retained[item.generation_id][2] for item in admitted]

    def _manifest_binding(self, authority, table, *, table_identity, qualified_table, history_epoch):
        if set(table) - {"anchored_profile"} != {"decoder", "partition_identity", "schema_fingerprint",
                                                "topic", "native_types", "start_offset"}:
            raise RuntimeBlocked("open_generation_manifest_required")
        if "capture_generation" in table["decoder"]:
            raise RuntimeBlocked("open_generation_manifest_required")
        _manifest_anchor(table)
        decoder_data = dict(table["decoder"], capture_generation=authority.capture_generation)
        decoder = PostgreSQLDecoder(**decoder_data)
        partition = PartitionIdentity(**table["partition_identity"])
        native_types = table["native_types"]
        if set(native_types) != set(decoder.columns) or type(table["start_offset"]) is not int:
            raise RuntimeBlocked("open_generation_manifest_invalid")
        aliases = {"timestamp without time zone": "timestamp", "timestamp with time zone": "timestamptz"}
        self._validate_topic(decoder, table["topic"], partition)
        return decoder_data, OpenGenerationBinding(
            authority=authority, object_id=table_identity, table_identity=decoder.table_identity,
            qualified_table=qualified_table, history_epoch=history_epoch,
            schema_fingerprint=table["schema_fingerprint"],
            columns={name: aliases.get(native_types[name], native_types[name]) for name in decoder.columns},
            key_columns=tuple(decoder.key_fields), partition_identity=partition, start_offset=table["start_offset"],
        )

    @contextmanager
    def _observe_committed(self, **request):
        try:
            with self.engine.connect() as connection:
                validate_target(connection.connection.driver_connection, expected_role="refraq_mirror_applier")
            timeout_ms = self.settings["target"]["timeout_seconds"] * 1000
            with Publication(self.engine, timeout_ms=timeout_ms).observe_committed(**request) as observed:
                yield observed
        except (MirrorError, RuntimeBlocked):
            raise
        except Exception:
            raise RuntimeBlocked("published_open_target_unconfirmed") from None

    def _resume_candidate(self, table, opened, checkpoint):
        binding = opened.binding
        expected = opened.identity
        observed = opened.observed
        _, manifest_binding = self._manifest_binding(
            binding.authority, table, table_identity=binding.table_identity,
            qualified_table=binding.qualified_table, history_epoch=binding.history_epoch,
        )
        if (manifest_binding.schema_fingerprint != binding.schema_fingerprint
                or manifest_binding.key_columns != binding.key_columns or manifest_binding.columns != binding.columns
                or observed.allocation["native_types"] != table["native_types"]):
            raise TablePrerequisiteFailed(binding.qualified_table, "schema")
        if manifest_binding != binding or tuple(manifest_binding.columns) != tuple(binding.columns):
            raise RuntimeBlocked("published_open_manifest_mismatch")
        evidence = observed.certificate["evidence"]
        profile = observed.allocation.get("anchored_profile")
        seal = observed.allocation.get("anchored_seal")
        authority = asdict(binding.authority)
        sealed_end = evidence["end_offset"] + 1
        seek = observed.applied_offset + 1
        if (not isinstance(profile, dict) or set(profile) != {"kind", "leader_epoch"}
                or profile.get("kind") != "disposable_read_committed_v1"
                or type(profile.get("leader_epoch")) is not int or profile["leader_epoch"] < 0
                or not _canonical_coverage(seal, authority=authority, leader_epoch=profile["leader_epoch"],
                                           earliest=binding.start_offset + 1, end=sealed_end, sealed=True)):
            raise RuntimeBlocked("published_open_seal_unconfirmed")
        original = json.dumps(seal, sort_keys=True)
        if original != json.dumps(evidence.get("ordered_delivery_proof"), sort_keys=True):
            raise RuntimeBlocked("published_open_seal_unconfirmed")
        if not _retained_coverage(observed.allocation, seal, authority, profile["leader_epoch"], seek):
            raise RuntimeBlocked("published_open_seal_unconfirmed")
        return RetainedOpenCandidate(opened.mirror_id, opened.operation_id, expected.generation_id, binding,
                                     table["topic"], expected.certificate_ref, checkpoint, seek)

    def _prepare_table(self, command, authority, table, opened):
        if opened is None:
            if not {"authority", "generation_id"} <= table.keys():
                raise RuntimeBlocked("current_mirror_open_required")
            return table
        if opened.get("reopen_baseline"):
            if table["partition_identity"] != opened["partition_identity"]:
                raise RuntimeBlocked("reopen_baseline_partition_changed")
            table = dict(table, start_offset=opened["start_offset"])
        elif "anchored_profile" in table and table["start_offset"] != -1:
            raise RuntimeBlocked("delivery_anchored_profile_invalid")
        decoder_data, expected = self._manifest_binding(
            authority, table, table_identity=opened["table_identity"], qualified_table=opened["qualified_table"],
            history_epoch=opened["history_epoch"],
        )
        request, proof, fence = self.signals.open_generation_proof(command, opened, table)
        if opened["assignment_fence_receipt"] is not None and opened["assignment_fence_receipt"] != fence:
            raise RuntimeBlocked("generation_assignment_fence_mismatch")
        installed = {**table, "decoder": decoder_data, "authority": asdict(authority), "open": opened,
                     "fence_receipt": fence}

        def verify_binding(*, binding, mirror_id, operation_id, mirror_revision):
            return (binding == expected and (mirror_id, operation_id, mirror_revision) ==
                    (opened["mirror_id"], opened["operation_id"], opened["mirror_revision"]))

        def allocate(*, generation_id, **_):
            self.signals.allocate_generation(command, request, proof, fence, generation_id)
            self._installed(dict(installed, generation_id=generation_id), command)
            return generation_id

        generation_id = reconcile_open_generation(
            mirror_id=opened["mirror_id"], operation_id=opened["operation_id"], binding=expected,
            verify_binding=verify_binding, allocate=allocate,
        )
        return dict(installed, generation_id=generation_id)

    def _require_current_allocations(self, session, authority, *, preparing=False):
        if not self.tables:
            raise RuntimeBlocked("retained_position_resume_driver_required")
        if self.retained and not preparing:
            if self.resume_operation_id is None:
                raise RuntimeBlocked("retained_position_resume_driver_required")
            candidates = [item[0] for item in self.retained.values()]
            require_current_retained_opens(session, authority=Authority(**_target_authority(authority)),
                                           published_scope=self.prepared_command["published_scope"],
                                           candidates=candidates,
                                           selected_table_ids={item.binding.table_identity for item in candidates})
        allocations = [(table["open"], table["generation_id"]) for table in self.tables
                       if "open" in table and table["generation_id"] not in self.retained]
        if allocations:
            require_current_open_allocations(session, authority=Authority(**_target_authority(authority)),
                                             allocations=allocations)

    def snapshot_bindings(self, command):
        if self.prepared_command != command:
            raise RuntimeBlocked("snapshot_preparation_superseded")
        snapshot = self.profile.snapshot
        return [SnapshotBinding(
            authority=Authority(**table["authority"]), mirror_id=opened["mirror_id"],
            mirror_revision=opened["mirror_revision"], allocation_operation_id=opened["operation_id"],
            generation_id=table["generation_id"], table_identity=opened["table_identity"],
            qualified_table=opened["qualified_table"], history_epoch=opened["history_epoch"],
            schema_fingerprint=table["schema_fingerprint"], data_partition=PartitionIdentity(**table["partition_identity"]),
            connector_name=self.profile.scope["topic_prefix"], signal_table=snapshot["signal_table"],
            signal_relation_identity=snapshot["signal_relation_identity"],
            notification_topic=snapshot["notification_topic"],
            notification_partition=PartitionIdentity(**snapshot["notification_partition"]),
        ) for table in self.tables if table["generation_id"] not in self.retained
          and (opened := table.get("open")) is not None]

    def recheck_snapshot_allocation(self, binding, *, session):
        command = self.prepared_command
        if command is None or binding not in self.snapshot_bindings(command):
            raise RuntimeBlocked("snapshot_preparation_superseded")
        table = next(table for table in self.tables if table["generation_id"] == binding.generation_id)
        try:
            mode = require_current_open_allocations(session, authority=binding.authority,
                                                    allocations=[(table["open"], binding.generation_id)])
            state = load_binding(session, binding.authority.source_id)
            snapshot = state.get("incremental_snapshots", {}).get("generations", {}).get(binding.generation_id)
            complete = bool(snapshot and snapshot["state"] == "catching_up" and snapshot["binding"] == asdict(binding))
            self._installed(table, command, observing_completion=complete)
        except RuntimeBlocked:
            raise
        except Exception:
            raise RuntimeBlocked("snapshot_allocation_unconfirmed") from None
        if binding.history_epoch != initial_history_epoch(binding.mirror_id) and (
            not table["open"].get("reopen_baseline")
            and (command["kind"] != "replace_owner" or command["operation_id"] != binding.allocation_operation_id)
        ):
            raise RuntimeBlocked("snapshot_replacement_allocation_unconfirmed")
        if command["kind"] == "replace_owner":
            return command, mode
        return command

    def validate_installation(self, command, *, session):
        self._load_installation()
        self._validate_manifest(command["published_scope"])
        authority = {key: command[key] for key in AUTHORITY_KEYS}
        try:
            self._require_current_allocations(session, authority, preparing=True)
            for table in self.tables:
                self._installed(table, authority)
        except RuntimeBlocked:
            raise
        except Exception:
            raise RuntimeBlocked("delivery_installation_unconfirmed") from None

    def _installed(self, table, authority, *, observing_completion=False):
        binding = DeliveryBinding(Authority(**table["authority"]), table["generation_id"],
                                  PartitionIdentity(**table["partition_identity"]), table["topic"])
        expected = _target_authority(authority)
        if asdict(binding.authority) != expected:
            raise RuntimeBlocked("delivery_manifest_authority_mismatch")
        decoder = PostgreSQLDecoder(**table["decoder"])
        binding.validate(decoder)
        try:
            metadata = target_metadata(self.engine, binding.generation_id)
        except Exception:
            raise RuntimeBlocked("delivery_installation_unconfirmed") from None
        opened = table.get("open")
        if (metadata and metadata["generation_id"] == binding.generation_id and metadata["authority"] == expected
                and metadata["table_identity"] == decoder.table_identity and (
                    metadata["schema_fingerprint"] != table["schema_fingerprint"] or metadata["key_columns"] != list(decoder.key_fields)
                    or metadata["column_names"] != list(decoder.columns) or metadata["native_types"] != table["native_types"])):
            raise TablePrerequisiteFailed(f"{decoder.source['schema']}.{decoder.source['table']}", "schema")
        if (metadata is None or metadata["authority"] != expected
                or metadata["generation_id"] != binding.generation_id
                or metadata["capture_generation"] != binding.authority.capture_generation
                or metadata["partition_identity"] != asdict(binding.partition_identity)
                or metadata["table_identity"] != decoder.table_identity
                or (opened is not None and (
                    metadata.get("fence_receipt") != table["fence_receipt"]
                    or metadata.get("start_offset") != table["start_offset"]
                    or any(metadata.get(key) != opened[key] for key in ("mirror_id", "operation_id", "history_epoch"))
                ))
                or metadata["cleanup_pending"] is not False
                or metadata["status"] not in {"building", "catching_up", "published"}):
            raise RuntimeBlocked("delivery_installed_metadata_mismatch")
        anchor = _manifest_anchor(table)
        retained = self.retained.get(binding.generation_id)
        if retained is not None:
            candidate, certificate, _ = retained
            seal = certificate["ordered_delivery_proof"]
            seek = metadata["applied_offset"] + 1
            if (anchor is None or metadata["status"] != "published"
                    or metadata.get("anchored_profile") != asdict(anchor) or metadata.get("anchored_seal") != seal
                    or seek < candidate.target_seek_offset
                    or not _retained_coverage(metadata, seal, asdict(candidate.binding.authority), anchor.leader_epoch, seek)):
                raise RuntimeBlocked("retained_position_target_changed")
        elif any(metadata.get(key) is not None for key in ("anchored_profile", "anchored_coverage", "anchored_seal")):
            if not observing_completion and (metadata["status"] == "published" or metadata.get("anchored_seal") is not None):
                raise RuntimeBlocked("retained_position_resume_driver_required")
            if anchor is None or opened is None or metadata.get("anchored_profile") != asdict(anchor):
                raise RuntimeBlocked("delivery_anchored_profile_mismatch")
            if not observing_completion and "eof" in (metadata.get("anchored_coverage") or {}):
                raise RuntimeBlocked("delivery_generation_sealed")
        elif anchor is not None:
            raise RuntimeBlocked("delivery_anchored_profile_mismatch")
        self._validate_topic(decoder, binding.topic, binding.partition_identity)
        return binding, decoder, metadata

    def _validate_topic(self, decoder, topic, partition):
        src = decoder.source
        scope = self.profile.scope
        if (src["db"] != scope["database"] or src["name"] != scope["topic_prefix"]
                or src["schema"] + "." + src["table"] not in scope["tables"]
                or topic != src["name"] + "." + src["schema"] + "." + src["table"]
                or type(partition.partition) is not int or partition.partition != 0):
            raise RuntimeBlocked("delivery_scope_mismatch")

    @contextmanager
    def admission(self, *, binding, decoder, limits):
        with self.journal.source_lock(self.source_id):
            with source_control_transaction(self.source_id) as (session, source):
                authority = self._current(session, source)
                table = next(t for t in self.tables if t["generation_id"] == binding.generation_id)
                current, installed, metadata = self._installed(table, authority)
                if current != binding or installed.key_schema != decoder.key_schema or installed.value_schema != decoder.value_schema:
                    raise RuntimeBlocked("delivery_binding_changed")
                # The gateway holds deployment exclusion until explicit release.
                # A signed snapshot alone is not a topic/producer exclusion lease.
                operation = uuid4().hex
                scope = {"profile": self.profile.scope, "table": table,
                         "target_metadata": metadata, "limits": asdict(limits),
                         "target_timeout_seconds": self.settings["target"]["timeout_seconds"]}
                if self.resume_operation_id is not None and binding.generation_id in self.retained:
                    candidate = self.retained[binding.generation_id][0]
                    scope["resume"] = dict(operation_id=self.resume_operation_id, certificate_ref=candidate.certificate_ref,
                                           history_epoch=candidate.binding.history_epoch)
                lease = None
                try:
                    result = self.signals.http.request("POST", "/v1/capture/delivery-leases", {
                        "operation_id": operation, "authority": authority, "scope": scope,
                    })
                    claims = self.verifier.verify(result["signature"], purpose="delivery_lease",
                                                  authority=authority, scope=scope, operation_id=operation)
                    now = time.time()
                    budget = (2 * limits.metadata_seconds + limits.poll_seconds
                              + 2 * self.settings["target"]["timeout_seconds"] + limits.metadata_seconds + 5)
                    if (claims.get("facts") != {key: True for key in FACTS}
                            or type(claims.get("observed_at")) not in {int, float}
                            or not math.isfinite(claims["observed_at"])
                            or not 0 <= now - claims["observed_at"] <= self.max_age
                            or type(claims.get("exp")) not in {int, float}
                            or claims["exp"] < now + budget
                            or not isinstance(claims.get("lease_id"), str) or not claims["lease_id"]):
                        raise RuntimeBlocked("delivery_lease_unproven")
                    lease = claims["lease_id"]
                    yield
                finally:
                    if lease is not None:
                        self.signals.http.request("POST", "/v1/capture/delivery-leases/release", {
                            "lease_id": lease, "operation_id": operation,
                        })

    def poll_once(self):
        try:
            with self.journal.source_lock(self.source_id):
                with source_control_transaction(self.source_id) as (session, source):
                    state = load_binding(session, self.source_id)
                    if state is None or state["desired"] == "stopped":
                        self.retire()
                        return 0
                    if self.resume_operation_id and not self.tables:
                        self.retire()
                        return 0
                    stamp = self._current(session, source)
                    generation_ids = {table["generation_id"] for table in self.tables}
                    if stamp != self.stamp or self.client_generations != generation_ids:
                        self.retire()
                        for table in self.tables:
                            binding, decoder, _ = self._installed(table, stamp)
                            options = {}
                            if self.resume_operation_id is not None and binding.generation_id in self.retained:
                                candidate, certificate, _ = self.retained[binding.generation_id]
                                options["resume"] = dict(certificate=certificate, history_epoch=candidate.binding.history_epoch)
                            self.clients.append(open_delivery(
                                kafka_config=self.settings["kafka"], group_id=self.settings["group_id"],
                                applier_engine=self.engine, binding=binding, decoder=decoder,
                                admission=self.admission, limits=self.limits, anchored_profile=_manifest_anchor(table),
                                **options,
                            ))
                        self.stamp = stamp
                        self.client_generations = generation_ids
            return sum(client.poll_once() for client in self.clients)
        except Exception:
            self.retire()
            raise RuntimeBlocked("capture_delivery_blocked") from None

    def retire(self):
        clients, self.clients = self.clients, []
        self.stamp = None
        for client in clients:
            try:
                client.close()
            except Exception:
                pass

    def stop(self):
        for client in self.clients:
            client.stop()

    def close(self):
        self.retire()
        if self.engine is not None:
            self.engine.dispose()
