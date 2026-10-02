"""One object per Attribute Type. Callers ask the object; they do not switch on the name."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Literal

from backend.entity.attribute_type.codec import (
    decode_bigint,
    decode_boolean,
    decode_date,
    decode_decimal,
    decode_json,
    decode_number,
    decode_text,
    decode_time,
    decode_timestamp,
    encode_bigint,
    encode_boolean,
    encode_date,
    encode_decimal,
    encode_dictionary,
    encode_json,
    encode_number,
    encode_string,
    encode_text,
    encode_time,
    encode_timestamp,
)
from backend.entity.errors import EntityAttributeInvalid

STRING_MAX_LENGTH_MIN = 1
STRING_MAX_LENGTH_MAX = 65535
DECIMAL_PRECISION_MIN = 1
DECIMAL_PRECISION_MAX = 1000

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_CONFIG_FIELD_ORDER = (
    "max_length",
    "precision",
    "scale",
    "dictionary_id",
    "target_entity_id",
)

ChangeClass = Literal["breaking", "non_breaking", "unchanged"]

_EQ_NE_NULL = ("eq", "ne", "is_null")
_EQ_NE_IN_NULL = ("eq", "ne", "in", "is_null")
_EQ_NE_IN_CONTAINS_NULL = ("eq", "ne", "in", "contains", "is_null")
_CMP = ("eq", "ne", "in", "gt", "gte", "lt", "lte", "is_null")


@dataclass(frozen=True, slots=True)
class ConfigChange:
    suffix: str
    old_value: Any
    new_value: Any
    change_class: ChangeClass


@dataclass(frozen=True, slots=True)
class _ConfigLimit:
    name: str
    kind: str
    minimum: int | None
    maximum: int | None
    at_most: str | None


def _reject_foreign(attr: Any, attribute_type: str, allowed: frozenset[str]) -> None:
    present = [
        key for key in _CONFIG_FIELD_ORDER if getattr(attr, key) is not None
    ]
    foreign = [key for key in present if key not in allowed]
    if foreign:
        raise EntityAttributeInvalid(
            f"Attribute '{attr.name}' of type {attribute_type} rejects config"
            f" {', '.join(foreign)}"
        )


def _reset_config(attr: Any, **fields: Any) -> Any:
    return replace(
        attr,
        max_length=fields.get("max_length"),
        precision=fields.get("precision"),
        scale=fields.get("scale"),
        dictionary_id=fields.get("dictionary_id"),
        target_entity_id=fields.get("target_entity_id"),
        codes=None,
    )


def _require_max_length(*, name: str, max_length: int | None) -> int:
    if max_length is None:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' of type string requires max_length"
        )
    if not isinstance(max_length, int) or isinstance(max_length, bool):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' max_length must be an integer"
        )
    if max_length < STRING_MAX_LENGTH_MIN or max_length > STRING_MAX_LENGTH_MAX:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' max_length must be between"
            f" {STRING_MAX_LENGTH_MIN} and {STRING_MAX_LENGTH_MAX} (got {max_length})"
        )
    return max_length


def _require_precision_scale(
    *,
    name: str,
    precision: int | None,
    scale: int | None,
) -> tuple[int, int]:
    if precision is None or scale is None:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' of type decimal requires precision and scale"
        )
    if not isinstance(precision, int) or isinstance(precision, bool):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' decimal precision must be an integer"
        )
    if not isinstance(scale, int) or isinstance(scale, bool):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' decimal scale must be an integer"
        )
    if precision < DECIMAL_PRECISION_MIN or precision > DECIMAL_PRECISION_MAX:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' decimal precision must be between"
            f" {DECIMAL_PRECISION_MIN} and {DECIMAL_PRECISION_MAX} (got {precision})"
        )
    if scale < 0 or scale > precision:
        raise EntityAttributeInvalid(
            f"Attribute '{name}' decimal scale must be between 0 and precision"
            f" (got {scale})"
        )
    return precision, scale


def _http_int(name: str, field: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EntityAttributeInvalid(
            f"Attribute '{name}' {field} must be an integer"
        )
    return value


def _stored_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("attribute config integer fields must be integers")
    return value


def _stored_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("dictionary_id must be a string")
    return value


def _enum_literal(code: str) -> str:
    escaped = code.replace("'", "''")
    return f"'{escaped}'"


class _AttributeType:
    def __init__(
        self,
        *,
        name: str,
        operators: tuple[str, ...],
        physical_template: str,
        physical_bare: str,
        encode: Any,
        decode: Any,
        allows_upsert_key: bool = True,
        reads: frozenset[str] = frozenset(),
        config_keys: frozenset[str] = frozenset(),
        config_limits: tuple[_ConfigLimit, ...] = (),
    ) -> None:
        self.name = name
        self.operators = operators
        self.physical_template = physical_template
        self.physical_bare = physical_bare
        self._encode = encode
        self._decode = decode
        self.allows_upsert_key = allows_upsert_key
        self.reads = reads
        self.config_keys = config_keys
        self.config_limits = config_limits

    def clean(self, attr: Any) -> Any:
        _reject_foreign(attr, self.name, self.config_keys)
        return _reset_config(attr)

    def stored_fields(self, config: dict[str, Any]) -> dict[str, Any]:
        del config
        return {}

    def parse_config(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        del name, config
        return {}

    def config_payload(self, attr: Any) -> dict[str, Any]:
        del attr
        return {}

    def physical_sql(self, attr: Any) -> str:
        names = _PLACEHOLDER.findall(self.physical_template)
        if not names:
            return self.physical_template
        values: dict[str, Any] = {}
        for field in names:
            value = getattr(attr, field)
            assert value is not None
            values[field] = value
        return self.physical_template.format(**values)

    def check_predicate(self, attr: Any, *, column: str) -> str | None:
        del attr, column
        return None

    def encode(
        self,
        attr: Any,
        raw: Any,
        *,
        codes: Any = None,
        as_filter: bool = False,
    ) -> Any:
        return self._encode(attr, raw, codes=codes, as_filter=as_filter)

    def decode(self, attr: Any, value: Any) -> Any:
        return self._decode(attr, value)

    def config_changes(self, before: Any, after: Any) -> tuple[ConfigChange, ...]:
        del before, after
        return ()


class _String(_AttributeType):
    def __init__(self) -> None:
        super().__init__(
            name="string",
            config_keys=frozenset({"max_length"}),
            operators=_EQ_NE_IN_CONTAINS_NULL,
            physical_template="VARCHAR({max_length})",
            physical_bare="VARCHAR",
            config_limits=(
                _ConfigLimit(
                    "max_length",
                    "int",
                    STRING_MAX_LENGTH_MIN,
                    STRING_MAX_LENGTH_MAX,
                    None,
                ),
            ),
            encode=encode_string,
            decode=decode_text,
        )

    def clean(self, attr: Any) -> Any:
        _reject_foreign(attr, self.name, self.config_keys)
        max_length = _require_max_length(name=attr.name, max_length=attr.max_length)
        return _reset_config(attr, max_length=max_length)

    def stored_fields(self, config: dict[str, Any]) -> dict[str, Any]:
        if "max_length" not in config:
            return {}
        return {"max_length": _stored_int(config.get("max_length"))}

    def parse_config(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        if "max_length" not in config:
            return {}
        return {"max_length": _http_int(name, "max_length", config.get("max_length"))}

    def config_payload(self, attr: Any) -> dict[str, Any]:
        return {"max_length": attr.max_length}

    def config_changes(self, before: Any, after: Any) -> tuple[ConfigChange, ...]:
        if before.max_length == after.max_length:
            return ()
        old = before.max_length
        new = after.max_length
        widening = old is not None and new is not None and new > old
        return (
            ConfigChange(
                suffix="config.max_length",
                old_value=old,
                new_value=new,
                change_class="non_breaking" if widening else "breaking",
            ),
        )


class _Decimal(_AttributeType):
    def __init__(self) -> None:
        super().__init__(
            name="decimal",
            config_keys=frozenset({"precision", "scale"}),
            operators=_CMP,
            physical_template="NUMERIC({precision},{scale})",
            physical_bare="NUMERIC",
            config_limits=(
                _ConfigLimit(
                    "precision",
                    "int",
                    DECIMAL_PRECISION_MIN,
                    DECIMAL_PRECISION_MAX,
                    None,
                ),
                _ConfigLimit("scale", "int", 0, DECIMAL_PRECISION_MAX, "precision"),
            ),
            encode=encode_decimal,
            decode=decode_decimal,
        )

    def clean(self, attr: Any) -> Any:
        _reject_foreign(attr, self.name, self.config_keys)
        precision, scale = _require_precision_scale(
            name=attr.name, precision=attr.precision, scale=attr.scale
        )
        return _reset_config(attr, precision=precision, scale=scale)

    def stored_fields(self, config: dict[str, Any]) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if "precision" in config:
            fields["precision"] = _stored_int(config.get("precision"))
        if "scale" in config:
            fields["scale"] = _stored_int(config.get("scale"))
        return fields

    def parse_config(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if "precision" in config:
            fields["precision"] = _http_int(name, "precision", config.get("precision"))
        if "scale" in config:
            fields["scale"] = _http_int(name, "scale", config.get("scale"))
        return fields

    def config_payload(self, attr: Any) -> dict[str, Any]:
        return {"precision": attr.precision, "scale": attr.scale}

    def config_changes(self, before: Any, after: Any) -> tuple[ConfigChange, ...]:
        found: list[ConfigChange] = []
        if before.precision != after.precision:
            found.append(
                ConfigChange(
                    suffix="config.precision",
                    old_value=before.precision,
                    new_value=after.precision,
                    change_class="breaking",
                )
            )
        if before.scale != after.scale:
            found.append(
                ConfigChange(
                    suffix="config.scale",
                    old_value=before.scale,
                    new_value=after.scale,
                    change_class="breaking",
                )
            )
        return tuple(found)


class _Dictionary(_AttributeType):
    def __init__(self) -> None:
        super().__init__(
            name="dictionary",
            config_keys=frozenset({"dictionary_id"}),
            operators=_EQ_NE_IN_NULL,
            reads=frozenset({"dictionary"}),
            physical_template="VARCHAR(64)",
            physical_bare="VARCHAR(64)",
            config_limits=(
                _ConfigLimit("dictionary_id", "string", None, None, None),
            ),
            encode=encode_dictionary,
            decode=decode_text,
        )

    def clean(self, attr: Any) -> Any:
        _reject_foreign(attr, self.name, self.config_keys)
        dictionary_id = (attr.dictionary_id or "").strip()
        if not dictionary_id:
            raise EntityAttributeInvalid(
                f"Attribute '{attr.name}' of type dictionary requires dictionary_id"
            )
        return _reset_config(attr, dictionary_id=dictionary_id)

    def stored_fields(self, config: dict[str, Any]) -> dict[str, Any]:
        if "dictionary_id" not in config:
            return {}
        return {"dictionary_id": _stored_str(config.get("dictionary_id"))}

    def parse_config(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        if "dictionary_id" not in config:
            return {}
        value = config.get("dictionary_id")
        if not isinstance(value, str):
            raise EntityAttributeInvalid(
                f"Attribute '{name}' dictionary_id must be a string"
            )
        return {"dictionary_id": value.strip()}

    def config_payload(self, attr: Any) -> dict[str, Any]:
        return {"dictionary_id": attr.dictionary_id}

    def check_predicate(self, attr: Any, *, column: str) -> str | None:
        if not attr.codes:
            raise ValueError(f"dictionary attribute {attr.name!r} has no codes")
        literals = ", ".join(_enum_literal(code) for code in attr.codes)
        return f"{column} IS NULL OR {column} IN ({literals})"

    def config_changes(self, before: Any, after: Any) -> tuple[ConfigChange, ...]:
        before_codes = tuple(before.codes or ())
        after_codes = tuple(after.codes or ())
        before_set = set(before_codes)
        after_set = set(after_codes)
        added = sorted(after_set - before_set)
        removed = sorted(before_set - after_set)
        same_list = before.dictionary_id == after.dictionary_id
        if before_set == after_set and same_list:
            return ()
        if before_set == after_set:
            change_class: ChangeClass = "unchanged"
        elif not removed:
            change_class = "non_breaking"
        else:
            change_class = "breaking"
        return (
            ConfigChange(
                suffix="config.dictionary",
                old_value={
                    "dictionary_id": before.dictionary_id,
                    "codes": list(before_codes),
                },
                new_value={
                    "dictionary_id": after.dictionary_id,
                    "codes": list(after_codes),
                    "added": added,
                    "removed": removed,
                },
                change_class=change_class,
            ),
        )


class _Reference(_AttributeType):
    def __init__(self) -> None:
        super().__init__(
            name="reference",
            config_keys=frozenset({"target_entity_id"}),
            operators=_CMP,
            reads=frozenset({"target"}),
            physical_template="BIGINT",
            physical_bare="BIGINT",
            config_limits=(
                _ConfigLimit("target_entity_id", "string", None, None, None),
            ),
            encode=encode_bigint,
            decode=decode_bigint,
        )

    def clean(self, attr: Any) -> Any:
        _reject_foreign(attr, self.name, self.config_keys)
        target = (attr.target_entity_id or "").strip()
        if not target:
            raise EntityAttributeInvalid(
                f"Attribute '{attr.name}' of type reference requires target_entity_id"
            )
        return _reset_config(attr, target_entity_id=target)

    def stored_fields(self, config: dict[str, Any]) -> dict[str, Any]:
        value = config.get("target_entity_id")
        if value is None:
            return {}
        return {"target_entity_id": str(value)}

    def parse_config(self, name: str, config: dict[str, Any]) -> dict[str, Any]:
        if "target_entity_id" not in config:
            return {}
        value = config.get("target_entity_id")
        if value is None:
            return {"target_entity_id": None}
        if not isinstance(value, str):
            raise EntityAttributeInvalid(
                f"Attribute '{name}' target_entity_id must be a string"
            )
        return {"target_entity_id": value.strip()}

    def config_payload(self, attr: Any) -> dict[str, Any]:
        return {"target_entity_id": attr.target_entity_id}

    def config_changes(self, before: Any, after: Any) -> tuple[ConfigChange, ...]:
        if before.target_entity_id == after.target_entity_id:
            return ()
        return (
            ConfigChange(
                suffix="config.target_entity_id",
                old_value=before.target_entity_id,
                new_value=after.target_entity_id,
                change_class="breaking",
            ),
        )


_TYPES: tuple[_AttributeType, ...] = (
    _String(),
    _AttributeType(
        name="text",
        operators=_EQ_NE_IN_CONTAINS_NULL,
        physical_template="TEXT",
        physical_bare="TEXT",
        encode=encode_text,
        decode=decode_text,
    ),
    _AttributeType(
        name="integer",
        operators=_CMP,
        physical_template="BIGINT",
        physical_bare="BIGINT",
        encode=encode_bigint,
        decode=decode_bigint,
    ),
    _Decimal(),
    _AttributeType(
        name="number",
        operators=_CMP,
        allows_upsert_key=False,
        physical_template="DOUBLE PRECISION",
        physical_bare="DOUBLE PRECISION",
        encode=encode_number,
        decode=decode_number,
    ),
    _AttributeType(
        name="boolean",
        operators=_EQ_NE_NULL,
        physical_template="BOOLEAN",
        physical_bare="BOOLEAN",
        encode=encode_boolean,
        decode=decode_boolean,
    ),
    _AttributeType(
        name="date",
        operators=_CMP,
        physical_template="DATE",
        physical_bare="DATE",
        encode=encode_date,
        decode=decode_date,
    ),
    _AttributeType(
        name="timestamp",
        operators=_CMP,
        physical_template="TIMESTAMPTZ",
        physical_bare="TIMESTAMPTZ",
        encode=encode_timestamp,
        decode=decode_timestamp,
    ),
    _AttributeType(
        name="time",
        operators=_CMP,
        physical_template="TIME",
        physical_bare="TIME",
        encode=encode_time,
        decode=decode_time,
    ),
    _AttributeType(
        name="json",
        operators=_EQ_NE_NULL,
        allows_upsert_key=False,
        physical_template="JSONB",
        physical_bare="JSONB",
        encode=encode_json,
        decode=decode_json,
    ),
    _Dictionary(),
    _Reference(),
)
_BY_NAME = {item.name: item for item in _TYPES}


def resolve(name: str | None) -> _AttributeType:
    key = name or ""
    found = _BY_NAME.get(key)
    if found is None:
        raise EntityAttributeInvalid(
            f"Attribute type '{key}' is not in the closed set"
            if key
            else "Attribute type is required"
        )
    return found


def export_catalog() -> list[dict[str, Any]]:
    """Closed set, config limits, and physical templates for Console codegen."""
    rows: list[dict[str, Any]] = []
    for spec in _TYPES:
        rows.append(
            {
                "name": spec.name,
                "config": [
                    {
                        "name": limit.name,
                        "kind": limit.kind,
                        "minimum": limit.minimum,
                        "maximum": limit.maximum,
                        "at_most": limit.at_most,
                    }
                    for limit in spec.config_limits
                ],
                "physical": {
                    "template": spec.physical_template,
                    "bare": spec.physical_bare,
                },
            }
        )
    return rows
