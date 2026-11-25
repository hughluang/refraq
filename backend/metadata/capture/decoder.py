"""Strict schema-bearing Debezium JSON transport decoder with per-engine dialect data."""

import base64
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from backend.metadata.capture.runtime_store import RuntimeBlocked
from backend.metadata.mirrors.types import Record


TOAST = "__debezium_unavailable_value"
INTEGER_BITS = {"int8": 8, "int16": 16, "int32": 32, "int64": 64}
LOGICAL_TYPES = {
    "org.apache.kafka.connect.data.Decimal": "bytes",
    "io.debezium.time.Date": "int32",
    "io.debezium.time.MicroTime": "int64",
    "io.debezium.time.MicroTimestamp": "int64",
    "io.debezium.time.Timestamp": "int64",
    "io.debezium.time.ZonedTimestamp": "string",
    "io.debezium.data.Uuid": "string",
    "io.debezium.data.Json": "string",
}


@dataclass(frozen=True)
class DebeziumDialect:
    """Engine facts the decoder needs; carries data only, no behavior hooks.

    ``schema_in_source`` is false for engines whose Debezium source block has no
    schema member (MySQL): the catalog schema is then the database itself.
    ``unavailable`` is the connector's placeholder for an unchanged large value.
    ``partial_before`` admits null non-key old values (PostgreSQL replica identity DEFAULT).
    """

    engine: str
    connector: str
    schema_in_source: bool
    unavailable: str | None
    baseline_markers: tuple[str, ...]
    partial_before: bool
    extra_logical: dict = field(default_factory=dict)

    @property
    def error_code(self):
        return f"{self.engine}_delivery_invalid"

    @property
    def logical(self):
        return {**LOGICAL_TYPES, **self.extra_logical}


_TEMPORAL = {
    "io.debezium.time.Time": "int32",
    "io.debezium.time.NanoTime": "int64",
    "io.debezium.time.NanoTimestamp": "int64",
}
POSTGRESQL = DebeziumDialect("postgresql", "postgresql", True, TOAST, ("true", "last", "incremental"), True)
MYSQL = DebeziumDialect(
    "mysql", "mysql", False, None, ("true", "first", "first_in_data_collection", "last_in_data_collection", "last", "incremental"),
    False, {**_TEMPORAL, "io.debezium.time.Year": "int32", "io.debezium.data.Enum": "string",
            "io.debezium.data.EnumSet": "string"},
)
MSSQL = DebeziumDialect(
    "mssql", "sqlserver", True, None, ("true", "first", "first_in_data_collection", "last_in_data_collection", "last", "incremental"),
    False, dict(_TEMPORAL),
)
ORACLE = DebeziumDialect(
    "oracle", "oracle", True, TOAST, ("true", "first", "first_in_data_collection", "last_in_data_collection", "last", "incremental"),
    False, dict(_TEMPORAL),
)


class _Invalid(Exception):
    """Internal rejection; public entry points report one redacted engine code."""


def _blocked():
    raise _Invalid() from None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _blocked()
        result[key] = value
    return result


def _float(raw):
    value = float(raw)
    if not math.isfinite(value):
        _blocked()
    return value


def _decimal(raw):
    # Retain the admitted finite range while decoding the original decimal digits.
    _float(raw)
    return Decimal(raw)


def _json(raw):
    return json.loads(raw, object_pairs_hook=_pairs, parse_float=_float,
                      parse_constant=lambda _: _blocked())


def _same_schema(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
        right, sort_keys=True, allow_nan=False,
    )


def _fields(schema):
    if not isinstance(schema, dict) or schema.get("type") != "struct":
        _blocked()
    fields = schema.get("fields")
    if not isinstance(fields, list) or not fields:
        _blocked()
    result = {}
    for field in fields:
        name = field.get("field")
        if not isinstance(name, str) or not name or name in result:
            _blocked()
        result[name] = field
    return result


def _validate_scalar(schema, logical):
    kind = schema.get("type")
    name = schema.get("name")
    if "optional" in schema and type(schema["optional"]) is not bool:
        _blocked()
    if kind not in {*INTEGER_BITS, "float32", "float64", "boolean", "string", "bytes"}:
        _blocked()
    if name is not None and logical.get(name) != kind:
        _blocked()
    if name == "org.apache.kafka.connect.data.Decimal":
        parameters = schema.get("parameters", {})
        scale = int(parameters["scale"])
        if not -1000 <= scale <= 1000:
            _blocked()


def _unavailable(value, schema, marker):
    if marker is None:
        return False
    if schema["type"] == "string":
        return value == marker
    if schema["type"] == "bytes":
        return value == base64.b64encode(marker.encode()).decode()
    return False


def _exact_micros(value, factor):
    """Convert to microseconds; nanosecond values that would lose digits are rejected."""
    if factor is not None:
        return value * factor
    if value % 1000:
        _blocked()
    return value // 1000


def _scalar(value, schema):
    if value is None:
        if schema.get("optional") is not True:
            _blocked()
        return None
    kind, name = schema["type"], schema.get("name")
    if kind in INTEGER_BITS:
        bits = INTEGER_BITS[kind]
        if type(value) is not int or not -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
            _blocked()
    elif kind in {"float32", "float64"}:
        if (type(value) not in {int, float} or not math.isfinite(value)
                or kind == "float32" and abs(value) > 3.4028234663852886e38):
            _blocked()
    elif kind == "boolean":
        if type(value) is not bool:
            _blocked()
    elif kind in {"string", "bytes"} and not isinstance(value, str):
        _blocked()
    if kind in {"string", "bytes"} and "\x00" in value:
        _blocked()
    if name == "org.apache.kafka.connect.data.Decimal":
        raw = base64.b64decode(value, validate=True)
        if not raw:
            _blocked()
        # Decimal scaleb uses the ambient precision; use a local exact tuple instead.
        number = int.from_bytes(raw, "big", signed=True)
        scale = int(schema["parameters"]["scale"])
        return str(Decimal((int(number < 0), tuple(map(int, str(abs(number)))), -scale)))
    if kind == "bytes":
        return "\\x" + base64.b64decode(value, validate=True).hex()
    if name == "io.debezium.time.Date":
        return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(days=value)).date().isoformat()
    if name in {"io.debezium.time.MicroTimestamp", "io.debezium.time.Timestamp"}:
        micros = value if name.endswith("MicroTimestamp") else value * 1000
        return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=micros)).replace(tzinfo=None).isoformat()
    if name in {"io.debezium.time.MicroTime", "io.debezium.time.Time", "io.debezium.time.NanoTime"}:
        micros = _exact_micros(value, {"MicroTime": 1, "Time": 1000, "NanoTime": None}[name.rsplit(".", 1)[1]])
        if not 0 <= micros < 86400000000:
            _blocked()
        return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=micros)).time().isoformat()
    if name == "io.debezium.time.NanoTimestamp":
        micros = _exact_micros(value, None)
        return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=micros)).replace(tzinfo=None).isoformat()
    if name == "io.debezium.time.ZonedTimestamp":
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            _blocked()
        return parsed.astimezone(UTC).isoformat()
    if name == "io.debezium.data.Uuid":
        return str(UUID(value))
    if name == "io.debezium.data.Json":
        return json.loads(value, object_pairs_hook=_pairs, parse_float=_decimal, parse_constant=lambda _: _blocked())
    return value


class DebeziumDecoder:
    """An admitted immutable table/schema binding, not inferred from incoming data.

    Only the dialect's listed scalar Connect encodings are admitted. Schemas,
    including optionality and logical parameters, must match the installed
    generation. Subclasses only name their ``DIALECT``.
    """

    DIALECT: DebeziumDialect

    def __init__(self, *, table_identity, capture_generation, database, namespace,
                 schema_name, table_name, connector_version, key_schema, value_schema):
        dialect = self.DIALECT
        logical = dialect.logical
        try:
            self.key_fields = _fields(key_schema)
            envelope = _fields(value_schema)
            self.columns = _fields(envelope["after"])
            if (_fields(envelope["before"]) != self.columns
                    or not {"op", "source", "before", "after"} <= envelope.keys()
                    or not self.key_fields.keys() <= self.columns.keys()):
                _blocked()
            for name, field in self.columns.items():
                _validate_scalar(field, logical)
            for name, field in self.key_fields.items():
                _validate_scalar(field, logical)
                if field.get("optional", False):
                    _blocked()
                if ({k: v for k, v in field.items() if k != "optional"}
                        != {k: v for k, v in self.columns[name].items() if k != "optional"}):
                    _blocked()
            if not all(isinstance(v, str) and v for v in (
                table_identity, capture_generation, database, namespace,
                schema_name, table_name, connector_version,
            )):
                _blocked()
            if not dialect.schema_in_source and schema_name != database:
                _blocked()
            # Detach caller-owned schema dictionaries from the installed profile.
            self.key_schema = _json(json.dumps(key_schema))
            self.value_schema = _json(json.dumps(value_schema))
            self.key_fields = _fields(self.key_schema)
            self.columns = _fields(_fields(self.value_schema)["after"])
            self.table_identity = table_identity
            self.capture_generation = capture_generation
            self.source = {"connector": dialect.connector, "version": connector_version,
                           "name": namespace, "db": database, "table": table_name}
            if dialect.schema_in_source:
                self.source["schema"] = schema_name
            self.qualified_table = f"{schema_name}.{table_name}"
        except Exception:
            raise RuntimeBlocked(dialect.error_code) from None

    def decode(self, *, offset, key, value):
        dialect = self.DIALECT
        try:
            if type(offset) is not int or offset < 0:
                _blocked()
            key_doc = _json(key)
            if (set(key_doc) != {"schema", "payload"}
                    or not _same_schema(key_doc["schema"], self.key_schema)
                    or set(key_doc["payload"]) != set(self.key_fields)):
                _blocked()
            typed_key = {name: _scalar(key_doc["payload"][name], field)
                         for name, field in self.key_fields.items()}
            # Key fields are mandatory; only a logical JSON literal null decodes to None.
            json_null_keys = tuple(k for k, v in typed_key.items() if v is None)
            if any(
                _unavailable(key_doc["payload"][k], f, dialect.unavailable) for k, f in self.key_fields.items()
            ):
                _blocked()
            if value is None:
                return Record(offset, self.table_identity, self.capture_generation,
                              "tombstone", "live", typed_key, None, json_null_columns=json_null_keys)
            doc = _json(value)
            if set(doc) != {"schema", "payload"} or not _same_schema(doc["schema"], self.value_schema):
                _blocked()
            payload = doc["payload"]
            if set(payload) != set(_fields(self.value_schema)):
                _blocked()
            source, op = payload["source"], payload["op"]
            if any(source.get(k) != v for k, v in self.source.items()):
                _blocked()
            snapshot = source.get("snapshot")
            if op == "r" and (snapshot is True or snapshot in dialect.baseline_markers):
                origin = "baseline"
            elif op in {"c", "u", "d"} and (snapshot is False or snapshot == "false"):
                origin = "live"
            else:
                _blocked()
            before, after = payload["before"], payload["after"]
            if before is not None:
                if not isinstance(before, dict) or set(before) != set(self.columns):
                    _blocked()
                for k, v in before.items():
                    # Replica identity DEFAULT may omit old non-key values as null.
                    if k not in self.key_fields and (
                            (v is None and dialect.partial_before)
                            or _unavailable(v, self.columns[k], dialect.unavailable)):
                        continue
                    _scalar(v, self.columns[k])
                if any(_scalar(before[k], f) != typed_key[k] for k, f in self.key_fields.items()):
                    # A key change must arrive as ordered delete/tombstone/create.
                    _blocked()
            if op == "d":
                if before is None or after is not None:
                    _blocked()
                return Record(offset, self.table_identity, self.capture_generation,
                              "delete", origin, typed_key, None, json_null_columns=json_null_keys)
            if (op in {"c", "r"} and before is not None
                    or not isinstance(after, dict) or set(after) != set(self.columns)):
                _blocked()
            unchanged = tuple(k for k in self.columns if _unavailable(after[k], self.columns[k], dialect.unavailable))
            if unchanged and (op != "u" or set(unchanged) & self.key_fields.keys()):
                _blocked()
            values = {k: _scalar(v, self.columns[k]) for k, v in after.items() if k not in unchanged}
            json_nulls = tuple(k for k, v in values.items() if v is None and after[k] is not None
                               and self.columns[k].get("name") == "io.debezium.data.Json")
            if (any(values.get(k) != v for k, v in typed_key.items())
                    or set(json_nulls) & typed_key.keys() != set(json_null_keys)):
                _blocked()
            return Record(offset, self.table_identity, self.capture_generation,
                          "upsert", origin, typed_key, values, unchanged, json_nulls)
        except Exception:
            raise RuntimeBlocked(dialect.error_code) from None


class PostgreSQLDecoder(DebeziumDecoder):
    DIALECT = POSTGRESQL


class MySQLDecoder(DebeziumDecoder):
    DIALECT = MYSQL


class MSSQLDecoder(DebeziumDecoder):
    DIALECT = MSSQL


class OracleDecoder(DebeziumDecoder):
    DIALECT = ORACLE
