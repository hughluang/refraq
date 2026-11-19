"""Protected delivery installation and independent lease admission."""

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import math
import time
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.metadata.capture.control import (
    AUTHORITY_KEYS, included_tables, profile_matches_scope, source_control_transaction,
)
from backend.metadata.capture.decoder import PostgreSQLDecoder
from backend.metadata.capture.delivery import DeliveryBinding, DeliveryLimits, open_delivery
from backend.metadata.capture.runtime_store import RuntimeBlocked, protected_json, protected_read
from backend.metadata.capture.snapshot import SnapshotBinding
from backend.metadata.capture.store import load_binding
from backend.metadata.mirrors.bootstrap import validate_target
from backend.metadata.mirrors.publication import Publication
from backend.metadata.mirrors.service import (
    MirrorError, OpenGenerationBinding, current_open_preparations, initial_history_epoch, read_published_scope,
    reconcile_open_generation, require_current_open_allocations,
)
from backend.metadata.mirrors.types import Authority, PartitionIdentity


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

    def _current(self, session, source):
        state = load_binding(session, self.source_id)
        if (state is None or source.status != "active" or not source.capture_credential_ciphertext
                or source.capture_revision != state["credential_revision"]
                or state["desired"] != "configured" or state["owner_epoch"] <= 0
                or state["runtime_instance_id"] != self.signals.runtime_instance_id):
            raise RuntimeBlocked("delivery_current_authority_required")
        scope = read_published_scope(session, self.source_id)
        if scope != state.get("published_scope"):
            raise RuntimeBlocked("published_scope_changed")
        self._load_installation()
        self._validate_manifest(scope)
        self._require_current_allocations(session, state)
        return {key: state[key] for key in AUTHORITY_KEYS}

    def _validate_manifest(self, scope):
        expected = sorted((table["qualified_table"], table["table_identity"])
                          for table in included_tables(scope))
        try:
            actual = sorted((f'{decoder["schema_name"]}.{decoder["table_name"]}',
                             decoder["table_identity"])
                            for decoder in (table["decoder"] for table in self.manifest_tables))
        except (KeyError, TypeError):
            raise RuntimeBlocked("delivery_manifest_scope_mismatch") from None
        if actual != expected or not profile_matches_scope(self.profile.scope, scope):
            raise RuntimeBlocked("delivery_manifest_scope_mismatch")
        if getattr(self.profile, "snapshot", None) is not None:
            for table in self.manifest_tables:
                binding = table["partition_identity"]
                notification = self.profile.snapshot["notification_partition"]
                if (table["decoder"]["connector_version"] != "3.7.1.Final"
                        or binding["runtime_cluster_id"] != notification["runtime_cluster_id"]
                        or binding["topic_incarnation_id"] == notification["topic_incarnation_id"]):
                    raise RuntimeBlocked("delivery_snapshot_profile_mismatch")

    def prepare(self, command) -> tuple[RetainedOpenCandidate, ...]:
        """Prepare ordinary tables or recover the observed Source's sealed candidates."""
        self._load_installation()
        scope = command["published_scope"]
        self._validate_manifest(scope)
        authority = Authority(**_target_authority(command))
        if authority.source_id != self.source_id or authority.runtime_instance_id != self.signals.runtime_instance_id:
            raise RuntimeBlocked("delivery_current_authority_required")
        try:
            pending, applied = current_open_preparations(
                authority=authority, published_scope=scope, observe_committed=self._observe_committed,
            )
            if applied:
                manifest = {table["decoder"]["table_identity"]: table for table in self.manifest_tables}
                data_topics = {table["topic"] for table in self.manifest_tables}
                data_partitions = tuple(opened.binding.partition_identity for opened in applied)
                candidates = []
                prior_exclusion = None
                for opened in applied:
                    evidence = opened.observed.certificate["evidence"]
                    checkpoint = _confirmed_checkpoint(evidence, self.profile.scope,
                                                       data_topics=data_topics, data_partitions=data_partitions)
                    exclusion = evidence["producer_exclusion"]
                    if candidates and (checkpoint != candidates[0].source_checkpoint or exclusion != prior_exclusion):
                        raise RuntimeBlocked("published_open_checkpoint_unconfirmed")
                    prior_exclusion = exclusion
                    candidates.append(self._resume_candidate(manifest[opened.binding.table_identity], opened, checkpoint))
                self.tables = []
                self.prepared_command = command
                return tuple(candidates)
            opens = {opened["table_identity"]: opened for opened in pending}
            if (self.prepared_command == command and len(self.tables) == len(self.manifest_tables)
                    and all(table.get("open") == opens.get(table["decoder"]["table_identity"]) for table in self.tables)):
                return ()
            self.tables = [self._prepare_table(command, authority, table, opens.get(table["decoder"]["table_identity"]))
                           for table in self.manifest_tables]
        except (MirrorError, KeyError, TypeError, ValueError):
            self.prepared_command = None
            raise RuntimeBlocked("open_generation_preparation_blocked") from None
        except RuntimeBlocked:
            self.prepared_command = None
            raise
        self.prepared_command = command
        return ()

    def _manifest_binding(self, authority, table, *, table_identity, qualified_table, history_epoch):
        if set(table) != {"decoder", "partition_identity", "schema_fingerprint", "topic", "native_types", "start_offset"}:
            raise RuntimeBlocked("open_generation_manifest_required")
        if "capture_generation" in table["decoder"]:
            raise RuntimeBlocked("open_generation_manifest_required")
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
        if (manifest_binding != binding or tuple(manifest_binding.columns) != tuple(binding.columns)
                or observed.allocation["native_types"] != table["native_types"]):
            raise RuntimeBlocked("published_open_manifest_mismatch")
        evidence = observed.certificate["evidence"]
        profile = observed.allocation.get("anchored_profile")
        seal = observed.allocation.get("anchored_seal")
        seek = observed.applied_offset + 1
        if (not isinstance(profile, dict) or profile.get("kind") != "disposable_read_committed_v1"
                or type(profile.get("leader_epoch")) is not int or profile["leader_epoch"] < 0
                or not isinstance(seal, dict) or seal != observed.allocation.get("anchored_coverage")
                or seal != evidence.get("ordered_delivery_proof") or seal.get("authority") != asdict(binding.authority)
                or type(seal.get("eof")) is not int or seal["eof"] != seek or seal.get("end") != seek
                or evidence["end_offset"] != observed.applied_offset
                or any(seal.get(bound) != dict(low=0, stable=seek, high=seek, leader_epoch=profile["leader_epoch"])
                       for bound in ("before", "after"))):
            raise RuntimeBlocked("published_open_seal_unconfirmed")
        return RetainedOpenCandidate(opened.mirror_id, opened.operation_id, expected.generation_id, binding,
                                     table["topic"], expected.certificate_ref, checkpoint, seek)

    def _prepare_table(self, command, authority, table, opened):
        if opened is None:
            if not {"authority", "generation_id"} <= table.keys():
                raise RuntimeBlocked("current_mirror_open_required")
            return table
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

    def _require_current_allocations(self, session, authority):
        if not self.tables:
            raise RuntimeBlocked("retained_position_resume_driver_required")
        allocations = [(table["open"], table["generation_id"]) for table in self.tables if "open" in table]
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
        ) for table in self.tables if (opened := table.get("open")) is not None]

    def recheck_snapshot_allocation(self, binding, *, session):
        command = self.prepared_command
        if command is None or binding not in self.snapshot_bindings(command):
            raise RuntimeBlocked("snapshot_preparation_superseded")
        table = next(table for table in self.tables if table["generation_id"] == binding.generation_id)
        try:
            require_current_open_allocations(session, authority=binding.authority,
                                             allocations=[(table["open"], binding.generation_id)])
            self._installed(table, command)
        except RuntimeBlocked:
            raise
        except Exception:
            raise RuntimeBlocked("snapshot_allocation_unconfirmed") from None
        if binding.history_epoch != initial_history_epoch(binding.mirror_id):
            raise RuntimeBlocked("snapshot_replacement_allocation_unconfirmed")
        return command

    def validate_installation(self, command, *, session):
        self._load_installation()
        self._validate_manifest(command["published_scope"])
        authority = {key: command[key] for key in AUTHORITY_KEYS}
        try:
            self._require_current_allocations(session, authority)
            for table in self.tables:
                self._installed(table, authority)
        except RuntimeBlocked:
            raise
        except Exception:
            raise RuntimeBlocked("delivery_installation_unconfirmed") from None

    def _installed(self, table, authority):
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
        if (metadata is None or metadata["authority"] != expected
                or metadata["generation_id"] != binding.generation_id
                or metadata["capture_generation"] != binding.authority.capture_generation
                or metadata["partition_identity"] != asdict(binding.partition_identity)
                or metadata["table_identity"] != decoder.table_identity
                or metadata["schema_fingerprint"] != table["schema_fingerprint"]
                or metadata["key_columns"] != list(decoder.key_fields)
                or metadata["column_names"] != list(decoder.columns)
                or metadata["native_types"] != table["native_types"]
                or (opened is not None and (
                    metadata.get("fence_receipt") != table["fence_receipt"]
                    or metadata.get("start_offset") != table["start_offset"]
                    or any(metadata.get(key) != opened[key] for key in ("mirror_id", "operation_id", "history_epoch"))
                ))
                or metadata["cleanup_pending"] is not False
                or metadata["status"] not in {"building", "catching_up", "published"}):
            raise RuntimeBlocked("delivery_installed_metadata_mismatch")
        if any(metadata.get(key) is not None for key in ("anchored_profile", "anchored_coverage", "anchored_seal")):
            raise RuntimeBlocked("retained_position_resume_driver_required")
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
                    stamp = self._current(session, source)
                    if stamp != self.stamp:
                        self.retire()
                        for table in self.tables:
                            binding, decoder, _ = self._installed(table, stamp)
                            self.clients.append(open_delivery(
                                kafka_config=self.settings["kafka"], group_id=self.settings["group_id"],
                                applier_engine=self.engine, binding=binding, decoder=decoder,
                                admission=self.admission, limits=self.limits,
                            ))
                        self.stamp = stamp
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
