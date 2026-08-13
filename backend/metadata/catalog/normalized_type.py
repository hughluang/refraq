"""Closed Normalized Type derived from a native data_type string."""

from __future__ import annotations

import re

_PAREN = re.compile(r"\s*\(.*\)\s*$")
_SPACE = re.compile(r"\s+")

_STRING = frozenset(
    {
        "varchar",
        "nvarchar",
        "char",
        "nchar",
        "text",
        "ntext",
        "character varying",
        "character",
        "varchar2",
        "nvarchar2",
        "clob",
        "nclob",
        "long",
        "uuid",
        "uniqueidentifier",
        "xml",
        "xmltype",
        "citext",
        "name",
        "bpchar",
    }
)
_INTEGER = frozenset(
    {
        "integer",
        "int",
        "int2",
        "int4",
        "int8",
        "int16",
        "int32",
        "int64",
        "smallint",
        "bigint",
        "tinyint",
        "serial",
        "smallserial",
        "bigserial",
        "pls_integer",
        "binary_integer",
    }
)
_NUMBER = frozenset(
    {
        "numeric",
        "decimal",
        "number",
        "float",
        "float4",
        "float8",
        "real",
        "double",
        "double precision",
        "money",
        "smallmoney",
        "binary_float",
        "binary_double",
    }
)
_BOOLEAN = frozenset({"boolean", "bool", "bit"})
_DATE = frozenset({"date"})
_TIMESTAMP = frozenset(
    {
        "timestamp",
        "timestamptz",
        "timestamp without time zone",
        "timestamp with time zone",
        "datetime",
        "datetime2",
        "smalldatetime",
        "datetimeoffset",
        "time",
        "timetz",
        "time without time zone",
        "time with time zone",
        "interval",
        "interval year to month",
        "interval day to second",
    }
)
_BINARY = frozenset(
    {
        "bytea",
        "binary",
        "varbinary",
        "image",
        "blob",
        "raw",
        "long raw",
        "bfile",
    }
)
_JSON = frozenset({"json", "jsonb", "jsontype"})


def normalize_type(data_type: str) -> str:
    """Map an engine-native type string to a closed Normalized Type."""
    if not data_type or not str(data_type).strip():
        return "unknown"
    base = _PAREN.sub("", str(data_type).strip().lower())
    base = _SPACE.sub(" ", base).strip()
    if base in _STRING:
        return "string"
    if base in _INTEGER:
        return "integer"
    if base in _NUMBER:
        return "number"
    if base in _BOOLEAN:
        return "boolean"
    if base in _DATE:
        return "date"
    if base in _TIMESTAMP:
        return "timestamp"
    if base in _BINARY:
        return "binary"
    if base in _JSON:
        return "json"
    if base.startswith("timestamp") or base.startswith("time "):
        return "timestamp"
    if base.startswith("interval"):
        return "timestamp"
    if base.startswith("varchar") or base.startswith("nvarchar") or base.startswith("char"):
        return "string"
    return "unknown"
