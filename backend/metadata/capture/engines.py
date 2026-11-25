"""Registry of Source engines that have a complete, conformance-tested capture path.

The registry is the single answer to "can this engine be mirrored". An engine is
registered only when its profile, decoder, checkpoint confirmer and gateway
contracts all exist and pass ``backend/tests/test_capture_engine_conformance.py``.
Registration is not qualification of a database version or topology.

Callers outside this package ask two management questions, ``mirror_eligible`` and
``capture_authorized``, and never name an engine themselves.
"""

from dataclasses import dataclass
from typing import Any, Callable

from backend.metadata.capture import checkpoints
from backend.metadata.capture.decoder import MSSQLDecoder, MySQLDecoder, OracleDecoder, PostgreSQLDecoder
from backend.metadata.capture.mssql import MSSQLCaptureProfile
from backend.metadata.capture.mysql import MySQLCaptureProfile
from backend.metadata.capture.oracle import OracleCaptureProfile
from backend.metadata.capture.postgresql import PostgreSQLCaptureProfile
from backend.metadata.capture.runtime_store import RuntimeBlocked


@dataclass(frozen=True)
class CaptureEngine:
    """One engine's capture path. Fields are data or a single callable per seam; behavior lives in the adapters.

    ``profile`` builds the pinned scope and generates the connector configuration;
    ``decoder`` binds one table's Debezium envelope to ``Record``; ``topic`` names the
    topic a bound table must arrive on; ``checkpoint`` confirms the publication
    hand-off position; ``baseline_keys`` are the independent observations a
    replacement owner must prove.
    """

    code: str
    profile_key: str
    profile: Callable[..., Any]
    decoder: Callable[..., Any]
    topic: Callable[[dict], str]
    checkpoint: Callable[..., Any]
    baseline_keys: frozenset


def _topic(*parts):
    def build(source):
        return ".".join(source[part] for part in parts)
    return build


_REGISTRY = {engine.code: engine for engine in (
    CaptureEngine("postgresql", "postgresql_profile", PostgreSQLCaptureProfile, PostgreSQLDecoder,
                  _topic("name", "schema", "table"), checkpoints.confirm_postgresql,
                  frozenset({"postgresql", "wal", "slot", "connect", "kafka", "task_running"})),
    CaptureEngine("mysql", "mysql_profile", MySQLCaptureProfile, MySQLDecoder,
                  _topic("name", "db", "table"), checkpoints.confirm_mysql,
                  frozenset({"mysql", "binlog", "server_identity", "connect", "kafka", "task_running"})),
    CaptureEngine("mssql", "mssql_profile", MSSQLCaptureProfile, MSSQLDecoder,
                  _topic("name", "db", "schema", "table"), checkpoints.confirm_mssql,
                  frozenset({"mssql", "cdc", "lsn", "connect", "kafka", "task_running"})),
    CaptureEngine("oracle", "oracle_profile", OracleCaptureProfile, OracleDecoder,
                  _topic("name", "schema", "table"), checkpoints.confirm_oracle,
                  frozenset({"oracle", "redo", "scn", "connect", "kafka", "task_running"})),
)}
CAPTURE_ENGINE_CODES = frozenset(_REGISTRY)


def engine_for_entry(entry):
    """The one engine whose ``<engine>_profile`` the runtime Source entry configures."""
    matches = [engine for engine in _REGISTRY.values() if engine.profile_key in entry]
    if len(matches) != 1:
        raise RuntimeBlocked("explicit_capture_engine_required")
    return matches[0]


def mirror_eligible(*, source_kind, engine, object_type, is_present):
    """A present database table of an engine with a registered capture path may be mirrored."""
    return source_kind == "database" and engine in _REGISTRY and is_present and object_type == "table"


def capture_authorized(source, *, credential_revision):
    """The Source is active, mirrorable and holds the capture credential revision under consideration."""
    return (source is not None and source.status == "active" and source.engine in _REGISTRY
            and bool(source.capture_credential_ciphertext) and source.capture_revision == credential_revision)
