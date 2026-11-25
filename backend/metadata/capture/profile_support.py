"""Shared construction, admission and Debezium configuration rules for non-PostgreSQL capture profiles.

An engine profile pins one explicit, DBA-approved capture scope. It never
creates publications, CDC instances, supplemental logging, signal tables or
other source objects; it only observes them and blocks on anything it cannot
prove. Subclasses supply the engine's pinned scope keys, observation queries
and connector options.
"""

import json
import re
from contextlib import contextmanager
from typing import Callable

from backend.core.secrets import decrypt_secret
from backend.metadata.capture.runtime_store import RuntimeBlocked, TablePrerequisiteFailed
from backend.metadata.capture.scope import selected_tables

FILE_REF = re.compile(r"\$\{file:/[A-Za-z0-9_./-]+:[A-Za-z0-9_.-]+\}")
_IDENTITY = re.compile(r"[A-Za-z0-9:_.-]{1,128}")
_TOPIC = re.compile(r"[a-zA-Z0-9_.-]{1,249}")
_BOOTSTRAP = re.compile(r"[A-Za-z0-9.-]+:[0-9]{1,5}(?:,[A-Za-z0-9.-]+:[0-9]{1,5})*")
HISTORY_SECURITY = frozenset({
    "security.protocol", "ssl.endpoint.identification.algorithm", "ssl.truststore.location",
    "ssl.truststore.password", "ssl.keystore.location", "ssl.keystore.password", "ssl.key.password",
})
COMMON_SCOPE = frozenset({"source_id", "connector_name", "host", "port", "database", "tables",
                          "topic_prefix", "server_version", "history"})
TLS_KEYS = frozenset({"ca_file", "truststore", "truststore_password"})
SNAPSHOT_KEYS = frozenset({"signal_table", "signal_relation_identity", "notification_topic", "notification_partition"})


def is_secret_ref(value):
    return isinstance(value, str) and FILE_REF.fullmatch(value) is not None


class CaptureProfileBase:
    """Template for an engine capture profile; ``scope`` is signed and sent to the gateway verbatim."""

    engine_code: str
    extra_scope: frozenset = frozenset()
    table_pattern: re.Pattern
    default_connect: Callable

    def __init__(self, *, scope, tls, connect=None):
        if (not isinstance(scope, dict) or set(scope) - {"snapshot"} != COMMON_SCOPE | self.extra_scope
                or not isinstance(tls, dict) or set(tls) != TLS_KEYS
                or any(not isinstance(tls[k], str) or not tls[k] for k in ("ca_file", "truststore"))
                or not is_secret_ref(tls["truststore_password"])
                or any(not isinstance(scope[k], str) or not scope[k]
                       for k in ("source_id", "connector_name", "host", "database", "server_version"))
                or type(scope["port"]) is not int or not 0 < scope["port"] < 65536
                or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", scope["host"])
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", scope["connector_name"])
                or not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", scope["topic_prefix"])
                or not isinstance(scope["tables"], list) or not scope["tables"]
                or len(set(scope["tables"])) != len(scope["tables"])
                or any(not isinstance(t, str) or not self.table_pattern.fullmatch(t) for t in scope["tables"])
                or not self._history_valid(scope["history"])):
            raise RuntimeBlocked(f"explicit_{self.engine_code}_profile_required")
        self.scope, self.tls = scope, tls
        self.connect = connect or self.default_connect
        self.snapshot = scope.get("snapshot")
        if "snapshot" in scope and not self._snapshot_valid(self.snapshot):
            raise RuntimeBlocked("explicit_snapshot_profile_required")
        self._validate_engine_scope()

    @staticmethod
    def _history_valid(history):
        security = history.get("security") if isinstance(history, dict) else None
        return (isinstance(history, dict) and set(history) == {"bootstrap_servers", "security"}
                and isinstance(history["bootstrap_servers"], str) and _BOOTSTRAP.fullmatch(history["bootstrap_servers"])
                and isinstance(security, dict) and security.get("security.protocol") == "SSL"
                and set(security) <= HISTORY_SECURITY
                and all(isinstance(v, str) and v for v in security.values())
                and all(is_secret_ref(v) for k, v in security.items() if k.endswith("password")))

    def _snapshot_valid(self, snapshot):
        s = self.scope
        if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_KEYS:
            return False
        topics = {f'{s["topic_prefix"]}.{t}' for t in (*s["tables"], snapshot.get("signal_table"))}
        return (isinstance(snapshot["signal_table"], str) and self.table_pattern.fullmatch(snapshot["signal_table"]) is not None
                and snapshot["signal_table"] not in s["tables"]
                and isinstance(snapshot["signal_relation_identity"], str)
                and _IDENTITY.fullmatch(snapshot["signal_relation_identity"]) is not None
                and isinstance(snapshot["notification_topic"], str)
                and _TOPIC.fullmatch(snapshot["notification_topic"]) is not None
                and snapshot["notification_topic"] not in {".", ".."} | topics
                and isinstance(snapshot["notification_partition"], dict))

    # -- engine hooks -------------------------------------------------------------------------
    def _validate_engine_scope(self):
        """Raise ``RuntimeBlocked`` when engine-specific scope members are invalid."""

    def _access_matches(self, access):
        """Return whether the Source's ordinary access document names this exact endpoint and scope."""
        raise NotImplementedError

    def _connect_options(self):
        """Extra connection keywords the engine's driver needs beyond the common set."""
        return {}

    def _inspect(self, connection):
        """Observe prerequisites through the capture identity: (result by key, table failures).

        A result is ``True`` only when proven; an unobserved prerequisite blocks exactly like a failing one.
        An exception leaves the whole Source unconfirmed.
        """
        raise NotImplementedError

    def _connector(self, tables):
        """Engine-specific Debezium properties for the included tables."""
        raise NotImplementedError

    def collection_id(self, qualified_table):
        """The connector's data-collection id for a qualified table (signal and notification identity)."""
        return qualified_table

    # -- shared behavior ----------------------------------------------------------------------
    @property
    def included_tables(self):
        return [*self.scope["tables"], self.snapshot["signal_table"]] if self.snapshot else self.scope["tables"]

    def validate_source(self, source):
        p = self.scope
        if source.engine != self.engine_code or source.id != p["source_id"]:
            raise RuntimeBlocked(f"{self.engine_code}_scope_mismatch")
        unconfirmed = RuntimeBlocked(f"{self.engine_code}_readiness_unconfirmed")
        try:
            access = json.loads(decrypt_secret(source.access_ciphertext))
            if not self._access_matches(access):
                raise ValueError()
            credential = json.loads(decrypt_secret(source.capture_credential_ciphertext))
            with self.connect(host=p["host"], port=p["port"], database=p["database"], tls=self.tls,
                              username=credential["username"], password=credential["password"],
                              timeout=10, **self._connect_options()) as connection:
                results, failures = self._inspect(connection)
        except Exception:
            raise unconfirmed from None
        if failures:
            table, cause = failures[0]
            raise TablePrerequisiteFailed(table, cause, unconfirmed.args[0])
        if any(value is not True for value in results.values()):
            raise unconfirmed

    def configuration(self, command, source, refs):
        self.validate_source(source)
        tables = [entry["qualified_table"] for entry in selected_tables(self.scope, command["published_scope"])]
        if not tables:
            raise RuntimeBlocked("connector_published_scope_mismatch")
        if self.snapshot:
            tables.append(self.snapshot["signal_table"])
        p, history = self.scope, self.scope["history"]
        config = {
            "tasks.max": "1", "database.hostname": p["host"], "database.port": str(p["port"]),
            "database.user": refs["username"], "database.password": refs["password"],
            "topic.prefix": p["topic_prefix"], "snapshot.mode": "no_data",
            "tombstones.on.delete": "true", "decimal.handling.mode": "precise",
            "include.schema.changes": "true",
            "schema.history.internal.kafka.bootstrap.servers": history["bootstrap_servers"],
            "schema.history.internal.kafka.topic": p["topic_prefix"] + ".schema",
        }
        for role in ("producer", "consumer"):
            for key, value in history["security"].items():
                config[f"schema.history.internal.{role}.{key}"] = value
        if self.snapshot is not None:
            config.update({
                "signal.enabled.channels": "source",
                "signal.data.collection": self.collection_id(self.snapshot["signal_table"]),
                "incremental.snapshot.watermarking.strategy": "insert_insert",
                "notification.enabled.channels": "sink",
                "notification.sink.topic.name": self.snapshot["notification_topic"],
            })
        config.update(self._connector(tables))
        return config


@contextmanager
def disposed(engine):
    """Yield one SQLAlchemy connection and always release the engine."""
    try:
        with engine.connect() as connection:
            yield connection
    finally:
        engine.dispose()
