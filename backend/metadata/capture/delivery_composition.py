"""Protected delivery installation and independent lease admission."""

from contextlib import contextmanager
from dataclasses import asdict
import json
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
from backend.metadata.capture.store import load_binding
from backend.metadata.mirrors.bootstrap import validate_target
from backend.metadata.mirrors.service import read_published_scope
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
        self.settings, self.limits, self.max_age, self.tables = settings, limits, max_age, tables
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
        return {key: state[key] for key in AUTHORITY_KEYS}

    def _validate_manifest(self, scope):
        expected = sorted((table["qualified_table"], table["table_identity"])
                          for table in included_tables(scope))
        try:
            actual = sorted((f'{decoder["schema_name"]}.{decoder["table_name"]}',
                             decoder["table_identity"])
                            for decoder in (table["decoder"] for table in self.tables))
        except (KeyError, TypeError):
            raise RuntimeBlocked("delivery_manifest_scope_mismatch") from None
        if actual != expected or not profile_matches_scope(self.profile.scope, scope):
            raise RuntimeBlocked("delivery_manifest_scope_mismatch")

    def validate_installation(self, command):
        self._load_installation()
        self._validate_manifest(command["published_scope"])
        authority = {key: command[key] for key in AUTHORITY_KEYS}
        try:
            for table in self.tables:
                self._installed(table, authority)
        except RuntimeBlocked:
            raise
        except Exception:
            raise RuntimeBlocked("delivery_installation_unconfirmed") from None

    def _installed(self, table, authority):
        binding = DeliveryBinding(Authority(**table["authority"]), table["generation_id"],
                                  PartitionIdentity(**table["partition_identity"]), table["topic"])
        expected = {**authority, "resource_binding_id": authority["binding_id"],
                    "capture_generation": str(authority["capture_generation"])}
        del expected["binding_id"]
        if asdict(binding.authority) != expected:
            raise RuntimeBlocked("delivery_manifest_authority_mismatch")
        decoder = PostgreSQLDecoder(**table["decoder"])
        binding.validate(decoder)
        metadata = target_metadata(self.engine, binding.generation_id)
        if (metadata is None or metadata["authority"] != expected
                or metadata["generation_id"] != binding.generation_id
                or metadata["capture_generation"] != binding.authority.capture_generation
                or metadata["partition_identity"] != asdict(binding.partition_identity)
                or metadata["table_identity"] != decoder.table_identity
                or metadata["schema_fingerprint"] != table["schema_fingerprint"]
                or metadata["key_columns"] != list(decoder.key_fields)
                or metadata["column_names"] != list(decoder.columns)
                or metadata["native_types"] != table["native_types"]
                or metadata["cleanup_pending"] is not False
                or metadata["status"] not in {"building", "catching_up", "published"}):
            raise RuntimeBlocked("delivery_installed_metadata_mismatch")
        src = decoder.source
        scope = self.profile.scope
        if (src["db"] != scope["database"] or src["name"] != scope["topic_prefix"]
                or src["schema"] + "." + src["table"] not in scope["tables"]
                or binding.topic != src["name"] + "." + src["schema"] + "." + src["table"]
                or binding.partition_identity.partition != 0):
            raise RuntimeBlocked("delivery_scope_mismatch")
        return binding, decoder, metadata

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
