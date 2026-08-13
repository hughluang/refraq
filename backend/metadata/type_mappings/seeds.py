"""Product Type Mapping seeds. Occupies unique keys; does not insert a second row."""

from __future__ import annotations

from backend.core.time import utc_now
from backend.metadata.type_mappings.store import (
    TypeMappingRecord,
    get_type_mapping_store,
    new_type_mapping_id,
)

__all__ = [
    "PRODUCT_TYPE_MAPPING_SEEDS",
    "ensure_product_type_mappings",
]


def _pairs(engine: str, mapping: dict[str, str]) -> tuple[tuple[str, str, str], ...]:
    return tuple((engine, native, target) for native, target in mapping.items())


_POSTGRESQL = {
    "character varying": "string",
    "character": "string",
    "varchar": "string",
    "char": "string",
    "text": "string",
    "name": "string",
    "bpchar": "string",
    "uuid": "string",
    "xml": "string",
    "citext": "string",
    "integer": "integer",
    "int": "integer",
    "int2": "integer",
    "int4": "integer",
    "int8": "integer",
    "smallint": "integer",
    "bigint": "integer",
    "serial": "integer",
    "smallserial": "integer",
    "bigserial": "integer",
    "numeric": "number",
    "decimal": "number",
    "real": "number",
    "double precision": "number",
    "money": "number",
    "float4": "number",
    "float8": "number",
    "boolean": "boolean",
    "bool": "boolean",
    "date": "date",
    "timestamp": "timestamp",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamp",
    "timestamptz": "timestamp",
    "time": "time",
    "time without time zone": "time",
    "time with time zone": "time",
    "timetz": "time",
    "interval": "interval",
    "bytea": "binary",
    "bit": "binary",
    "bit varying": "binary",
    "varbit": "binary",
    "json": "json",
    "jsonb": "json",
    "integer[]": "array",
    "bigint[]": "array",
    "smallint[]": "array",
    "text[]": "array",
    "character varying[]": "array",
    "character[]": "array",
    "boolean[]": "array",
    "date[]": "array",
    "uuid[]": "array",
    "jsonb[]": "array",
    "json[]": "array",
    "numeric[]": "array",
    "bytea[]": "array",
    "timestamp without time zone[]": "array",
    "timestamp with time zone[]": "array",
}

_MSSQL = {
    "varchar": "string",
    "nvarchar": "string",
    "char": "string",
    "nchar": "string",
    "text": "string",
    "ntext": "string",
    "uniqueidentifier": "string",
    "xml": "string",
    "sysname": "string",
    "int": "integer",
    "bigint": "integer",
    "smallint": "integer",
    "tinyint": "integer",
    "decimal": "number",
    "numeric": "number",
    "float": "number",
    "real": "number",
    "money": "number",
    "smallmoney": "number",
    "bit": "boolean",
    "date": "date",
    "datetime": "timestamp",
    "datetime2": "timestamp",
    "datetimeoffset": "timestamp",
    "smalldatetime": "timestamp",
    "time": "time",
    "binary": "binary",
    "varbinary": "binary",
    "image": "binary",
    "timestamp": "binary",
    "rowversion": "binary",
}

_ORACLE = {
    "varchar2": "string",
    "nvarchar2": "string",
    "char": "string",
    "nchar": "string",
    "clob": "string",
    "nclob": "string",
    "long": "string",
    "xmltype": "string",
    "rowid": "string",
    "urowid": "string",
    "number": "number",
    "float": "number",
    "binary_float": "number",
    "binary_double": "number",
    "date": "timestamp",
    "timestamp": "timestamp",
    "timestamp with time zone": "timestamp",
    "timestamp with local time zone": "timestamp",
    "interval year to month": "interval",
    "interval day to second": "interval",
    "raw": "binary",
    "long raw": "binary",
    "blob": "binary",
    "bfile": "binary",
    "json": "json",
}

PRODUCT_TYPE_MAPPING_SEEDS: tuple[tuple[str, str, str], ...] = (
    _pairs("postgresql", _POSTGRESQL)
    + _pairs("mssql", _MSSQL)
    + _pairs("oracle", _ORACLE)
)


def ensure_product_type_mappings() -> None:
    """Occupy each product seed key. Refresh product rows; take over job/user rows."""
    store = get_type_mapping_store()
    now = utc_now()
    for engine, native_type, target in PRODUCT_TYPE_MAPPING_SEEDS:
        existing = store.get_by_key(engine, native_type)
        if existing is None:
            store.create(
                TypeMappingRecord(
                    id=new_type_mapping_id(),
                    engine=engine,
                    native_type=native_type,
                    normalized_type=target,
                    origin="product",
                    created_at=now,
                    updated_at=now,
                )
            )
            continue
        if (
            existing.origin == "product"
            and existing.normalized_type == target
        ):
            continue
        store.save(
            TypeMappingRecord(
                id=existing.id,
                engine=existing.engine,
                native_type=existing.native_type,
                normalized_type=target,
                origin="product",
                created_at=existing.created_at,
                updated_at=now,
            )
        )
