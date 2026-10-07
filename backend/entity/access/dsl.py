"""Row-rule DSL. Authors write a JSON tree; this module type-checks it and emits SQL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from backend.entity.access.facts import AttrFact, SubjectAttrFact
from backend.entity.attribute_type import resolve
from backend.entity.errors import EntityRowInvalid
from backend.entity.records import AttributeRecord

__all__ = [
    "LEAF_MAX",
    "DEPTH_MAX",
    "RuleInfo",
    "RuleProblem",
    "RuleWarning",
    "eval_rule",
    "rule_sql",
    "validate_rule",
]

LEAF_MAX = 20
DEPTH_MAX = 8
_GROUPS = frozenset({"and", "or", "not"})
_OPS = frozenset(
    {"eq", "ne", "lt", "lte", "gt", "gte", "in", "is_null", "contains"}
)
_CMP = frozenset({"lt", "lte", "gt", "gte"})
_DURATION = re.compile(
    r"^(?P<sign>-)?P"
    r"(?:(?P<y>\d+)Y)?(?:(?P<mo>\d+)M)?(?:(?P<d>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<mi>\d+)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?)?$"
)
_SQL_CMP = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
_SUBJECT_COMPAT = {
    "string": frozenset({"string", "text"}),
    "integer": frozenset({"integer"}),
    "date": frozenset({"date"}),
    "dictionary": frozenset({"dictionary"}),
    "user": frozenset({"user"}),
}


class RuleProblem(ValueError):
    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"{path}: {detail}")
        self.path = path
        self.detail = detail


@dataclass(frozen=True, slots=True)
class RuleWarning:
    path: str
    attribute_id: str
    message: str


@dataclass(frozen=True, slots=True)
class RuleInfo:
    attribute_ids: tuple[str, ...]
    subject_keys: tuple[str, ...]
    uses_subject_id: bool


def validate_rule(
    rule: Any,
    attrs: dict[str, AttrFact],
    subject_attrs: dict[str, SubjectAttrFact],
) -> RuleInfo:
    if rule is None:
        return RuleInfo((), (), False)
    leaves = [0]
    ids: list[str] = []
    keys: list[str] = []
    uses_subject = [False]
    _walk(
        rule,
        attrs,
        subject_attrs,
        path="$",
        depth=1,
        leaves=leaves,
        ids=ids,
        keys=keys,
        uses_subject=uses_subject,
    )
    return RuleInfo(tuple(ids), tuple(dict.fromkeys(keys)), uses_subject[0])


def rule_warnings(
    rule: Any,
    *,
    visible_attribute_ids: frozenset[str],
) -> tuple[RuleWarning, ...]:
    found: list[RuleWarning] = []
    _warn(rule, path="$", visible=visible_attribute_ids, found=found)
    return tuple(found)


def rule_sql(
    rule: Any,
    attrs: dict[str, AttrFact],
    *,
    alias: str,
    acl: bool,
    subject_id: str | None = None,
    subject_values: dict[str, tuple[Any, ...]] | None = None,
) -> str:
    if rule is None:
        return "TRUE"
    return _sql_node(
        rule,
        attrs,
        path="$",
        alias=alias,
        acl=acl,
        subject_id=subject_id,
        subject_values=subject_values or {},
    )


def eval_rule(
    rule: Any,
    row: dict[str, Any],
    attrs: dict[str, AttrFact],
    *,
    subject_id: str,
    subject_values: dict[str, tuple[Any, ...]],
    now: datetime,
) -> bool:
    if rule is None:
        return True
    return _eval_node(
        rule,
        row,
        attrs,
        path="$",
        subject_id=subject_id,
        subject_values=subject_values,
        now=now,
    )


def _walk(
    node: Any,
    attrs: dict[str, AttrFact],
    subject_attrs: dict[str, SubjectAttrFact],
    *,
    path: str,
    depth: int,
    leaves: list[int],
    ids: list[str],
    keys: list[str],
    uses_subject: list[bool],
) -> None:
    if depth > DEPTH_MAX:
        raise RuleProblem(path, "rule depth exceeds 8")
    if not isinstance(node, dict) or len(node) != 1:
        raise RuleProblem(path, "rule node must be a single-key object")
    key = next(iter(node))
    body = node[key]
    if key in _GROUPS:
        _walk_group(
            key,
            body,
            attrs,
            subject_attrs,
            path=path,
            depth=depth,
            leaves=leaves,
            ids=ids,
            keys=keys,
            uses_subject=uses_subject,
        )
        return
    if key not in _OPS:
        raise RuleProblem(path, f"unknown rule operator '{key}'")
    leaves[0] += 1
    if leaves[0] > LEAF_MAX:
        raise RuleProblem(path, "rule has more than 20 leaves")
    _walk_leaf(
        key,
        body,
        attrs,
        subject_attrs,
        path=f"{path}.{key}",
        ids=ids,
        keys=keys,
        uses_subject=uses_subject,
    )


def _walk_group(
    key: str,
    body: Any,
    attrs: dict[str, AttrFact],
    subject_attrs: dict[str, SubjectAttrFact],
    *,
    path: str,
    depth: int,
    leaves: list[int],
    ids: list[str],
    keys: list[str],
    uses_subject: list[bool],
) -> None:
    if key == "not":
        _walk(
            body,
            attrs,
            subject_attrs,
            path=f"{path}.not",
            depth=depth + 1,
            leaves=leaves,
            ids=ids,
            keys=keys,
            uses_subject=uses_subject,
        )
        return
    if not isinstance(body, list) or not body:
        raise RuleProblem(f"{path}.{key}", f"{key} must be a non-empty list")
    for index, item in enumerate(body):
        _walk(
            item,
            attrs,
            subject_attrs,
            path=f"{path}.{key}[{index}]",
            depth=depth + 1,
            leaves=leaves,
            ids=ids,
            keys=keys,
            uses_subject=uses_subject,
        )


def _walk_leaf(
    op: str,
    body: Any,
    attrs: dict[str, AttrFact],
    subject_attrs: dict[str, SubjectAttrFact],
    *,
    path: str,
    ids: list[str],
    keys: list[str],
    uses_subject: list[bool],
) -> None:
    if not isinstance(body, dict):
        raise RuleProblem(path, "leaf must be an object")
    attribute_id = body.get("attr")
    if not isinstance(attribute_id, str) or not attribute_id:
        raise RuleProblem(path, "attr must be an attribute id")
    attr = attrs.get(attribute_id)
    if attr is None:
        raise RuleProblem(path, f"unknown attribute '{attribute_id}'")
    ids.append(attribute_id)
    operand = _operand_name(body, path)
    if op == "is_null":
        if operand != "value" or not isinstance(body["value"], bool):
            raise RuleProblem(path, "is_null takes value true or false")
        return
    if operand == "subject_id":
        if body["subject_id"] is not True or op not in {"eq", "ne"}:
            raise RuleProblem(path, "subject_id is true and only eq or ne")
        if attr.type != "user":
            raise RuleProblem(path, "subject_id compares only a user attribute")
        uses_subject[0] = True
        return
    if operand == "subject_attr":
        if op != "in":
            raise RuleProblem(path, "subject_attr is only valid for in")
        key = body["subject_attr"]
        if not isinstance(key, str) or not key:
            raise RuleProblem(path, "subject_attr must be a key")
        subject = subject_attrs.get(key)
        if subject is None:
            raise RuleProblem(path, f"unknown subject attribute '{key}'")
        _subject_compatible(path, attr, subject)
        keys.append(key)
        return
    if operand == "rel_time":
        if op not in _CMP:
            raise RuleProblem(path, "rel_time is only valid for lt, lte, gt, and gte")
        if attr.value_type() not in {"date", "timestamp"}:
            raise RuleProblem(path, "rel_time compares only date or timestamp")
        _parse_duration(body["rel_time"], path, attr.value_type())
        return
    if operand != "value":
        raise RuleProblem(path, "leaf operand is missing")
    if op not in attr.operators():
        raise RuleProblem(
            path, f"operator '{op}' is not allowed for type {attr.type}"
        )
    _check_value(op, body["value"], attr, path)


def _operand_name(body: dict[str, Any], path: str) -> str:
    names = [key for key in body if key != "attr"]
    if len(names) != 1:
        raise RuleProblem(path, "leaf must name exactly one operand")
    return names[0]


def _subject_compatible(path: str, attr: AttrFact, subject: SubjectAttrFact) -> None:
    allowed = _SUBJECT_COMPAT.get(subject.value_type, frozenset())
    value_type = attr.value_type()
    if value_type not in allowed and not (
        attr.type == "reference" and value_type in allowed
    ):
        raise RuleProblem(
            path,
            f"subject attribute '{subject.key}' is not compatible with {attr.type}",
        )
    if attr.type == "dictionary" or subject.value_type == "dictionary":
        if attr.dictionary_id != subject.dictionary_id or not attr.dictionary_id:
            raise RuleProblem(
                path,
                "dictionary operands must share the attribute dictionary_id",
            )


def _check_value(op: str, raw: Any, attr: AttrFact, path: str) -> None:
    if op == "in":
        if not isinstance(raw, list) or not raw:
            raise RuleProblem(path, "in value must be a non-empty list")
        for index, item in enumerate(raw):
            _encode(item, attr, f"{path}.value[{index}]")
        return
    if op == "contains":
        if not isinstance(raw, str):
            raise RuleProblem(path, "contains value must be a string")
        return
    _encode(raw, attr, f"{path}.value")


def _encode(raw: Any, attr: AttrFact, path: str) -> Any:
    record = AttributeRecord(
        name=attr.name,
        type=attr.value_type() or attr.type,
        max_length=attr.reference_max_length
        if attr.type == "reference"
        else attr.max_length,
        precision=attr.precision,
        scale=attr.scale,
        dictionary_id=attr.dictionary_id,
        codes=attr.codes,
        attribute_id=attr.attribute_id,
    )
    kind = attr.value_type()
    if not kind:
        raise RuleProblem(path, f"attribute '{attr.attribute_id}' has no value type")
    try:
        return resolve(kind).encode(
            record, raw, codes=attr.codes, as_filter=True
        )
    except EntityRowInvalid as exc:
        raise RuleProblem(path, exc.message) from exc


def _warn(
    node: Any,
    *,
    path: str,
    visible: frozenset[str],
    found: list[RuleWarning],
) -> None:
    if not isinstance(node, dict) or len(node) != 1:
        return
    key = next(iter(node))
    body = node[key]
    if key == "not":
        _warn(body, path=f"{path}.not", visible=visible, found=found)
        return
    if key in {"and", "or"} and isinstance(body, list):
        for index, item in enumerate(body):
            _warn(item, path=f"{path}.{key}[{index}]", visible=visible, found=found)
        return
    if key not in _OPS or not isinstance(body, dict):
        return
    attribute_id = body.get("attr")
    if isinstance(attribute_id, str) and attribute_id not in visible:
        found.append(
            RuleWarning(
                path=f"{path}.{key}",
                attribute_id=attribute_id,
                message=(
                    "row visibility discloses that this hidden attribute "
                    "satisfies the rule"
                ),
            )
        )


def _sql_node(
    node: Any,
    attrs: dict[str, AttrFact],
    *,
    path: str,
    alias: str,
    acl: bool,
    subject_id: str | None,
    subject_values: dict[str, tuple[Any, ...]],
) -> str:
    key = next(iter(node))
    body = node[key]
    if key == "and":
        parts = [
            _sql_node(
                item,
                attrs,
                path=f"{path}.and[{index}]",
                alias=alias,
                acl=acl,
                subject_id=subject_id,
                subject_values=subject_values,
            )
            for index, item in enumerate(body)
        ]
        return "(" + " AND ".join(parts) + ")"
    if key == "or":
        parts = [
            _sql_node(
                item,
                attrs,
                path=f"{path}.or[{index}]",
                alias=alias,
                acl=acl,
                subject_id=subject_id,
                subject_values=subject_values,
            )
            for index, item in enumerate(body)
        ]
        return "(" + " OR ".join(parts) + ")"
    if key == "not":
        inner = _sql_node(
            body,
            attrs,
            path=f"{path}.not",
            alias=alias,
            acl=acl,
            subject_id=subject_id,
            subject_values=subject_values,
        )
        # A NULL leaf is false (as in eval_rule), so NOT of it is true.
        return f"(NOT COALESCE({inner}, false))"
    return _sql_leaf(
        key,
        body,
        attrs,
        alias=alias,
        acl=acl,
        subject_id=subject_id,
        subject_values=subject_values,
    )


def _sql_leaf(
    op: str,
    body: dict[str, Any],
    attrs: dict[str, AttrFact],
    *,
    alias: str,
    acl: bool,
    subject_id: str | None,
    subject_values: dict[str, tuple[Any, ...]],
) -> str:
    attr = attrs[str(body["attr"])]
    column = f'{alias}."{attr.name}"'
    if op == "is_null":
        return f"{column} IS NULL" if body["value"] else f"{column} IS NOT NULL"
    if "subject_id" in body:
        token = _subject_id_sql(acl, subject_id)
        if op == "ne":
            return f"{column} IS DISTINCT FROM {token}"
        return f"({column} = {token})"
    if "subject_attr" in body:
        return _in_subject_sql(
            column, attr, str(body["subject_attr"]), acl=acl, subject_values=subject_values
        )
    if "rel_time" in body:
        interval = _interval_sql(str(body["rel_time"]))
        clock = "CURRENT_DATE" if attr.value_type() == "date" else "CURRENT_TIMESTAMP"
        return f"({column} {_SQL_CMP[op]} ({clock} + {interval}))"
    if op == "in":
        encoded = [_encode(item, attr, "$") for item in body["value"]]
        literals = ", ".join(_literal(item, attr) for item in encoded)
        return f"({column} = ANY (ARRAY[{literals}]::{attr.pg_type()}[]))"
    if op == "contains":
        return f"({column} LIKE {_literal(_like(str(body['value'])), attr)} ESCAPE '\\')"
    encoded = _encode(body["value"], attr, "$")
    literal = _literal(encoded, attr)
    if op == "ne":
        return f"({column} IS DISTINCT FROM {literal})"
    if op == "eq":
        return f"({column} = {literal})"
    return f"({column} {_SQL_CMP[op]} {literal})"


def _subject_id_sql(acl: bool, subject_id: str | None) -> str:
    if acl:
        return "(SELECT acl.subject_text('__access_subject'))"
    return _quote(subject_id or "")


def _in_subject_sql(
    column: str,
    attr: AttrFact,
    key: str,
    *,
    acl: bool,
    subject_values: dict[str, tuple[Any, ...]],
) -> str:
    if acl:
        array = f"(SELECT acl.subject_text_array('{_escape(key)}'))"
        if attr.pg_type() == "text":
            return f"({column} = ANY ({array}))"
        return (
            f"({column} = ANY (SELECT v::{attr.pg_type()} "
            f"FROM unnest({array}) AS u(v)))"
        )
    values = subject_values.get(key, ())
    if not values:
        return "FALSE"
    literals = ", ".join(_literal(item, attr) for item in values)
    return f"({column} = ANY (ARRAY[{literals}]::{attr.pg_type()}[]))"


def _eval_node(
    node: Any,
    row: dict[str, Any],
    attrs: dict[str, AttrFact],
    *,
    path: str,
    subject_id: str,
    subject_values: dict[str, tuple[Any, ...]],
    now: datetime,
) -> bool:
    key = next(iter(node))
    body = node[key]
    if key == "and":
        return all(
            _eval_node(
                item,
                row,
                attrs,
                path=f"{path}.and[{index}]",
                subject_id=subject_id,
                subject_values=subject_values,
                now=now,
            )
            for index, item in enumerate(body)
        )
    if key == "or":
        return any(
            _eval_node(
                item,
                row,
                attrs,
                path=f"{path}.or[{index}]",
                subject_id=subject_id,
                subject_values=subject_values,
                now=now,
            )
            for index, item in enumerate(body)
        )
    if key == "not":
        return not _eval_node(
            body,
            row,
            attrs,
            path=f"{path}.not",
            subject_id=subject_id,
            subject_values=subject_values,
            now=now,
        )
    return _eval_leaf(
        key,
        body,
        row,
        attrs,
        subject_id=subject_id,
        subject_values=subject_values,
        now=now,
    )


def _eval_leaf(
    op: str,
    body: dict[str, Any],
    row: dict[str, Any],
    attrs: dict[str, AttrFact],
    *,
    subject_id: str,
    subject_values: dict[str, tuple[Any, ...]],
    now: datetime,
) -> bool:
    attr = attrs[str(body["attr"])]
    current = row.get(attr.name)
    if op == "is_null":
        return (current is None) if body["value"] else (current is not None)
    if "subject_id" in body:
        if current is None:
            return op == "ne"
        return (current != subject_id) if op == "ne" else current == subject_id
    if "subject_attr" in body:
        if current is None:
            return False
        return any(_same(current, item, attr) for item in subject_values.get(str(body["subject_attr"]), ()))
    if "rel_time" in body:
        if current is None:
            return False
        boundary = _shift(now, str(body["rel_time"]))
        left = _as_comparable(current, attr)
        right = boundary.date() if attr.value_type() == "date" else boundary
        return _cmp(op, left, right)
    if op == "in":
        if current is None:
            return False
        return any(_same(current, _encode(item, attr, "$"), attr) for item in body["value"])
    if op == "contains":
        if current is None:
            return False
        return str(body["value"]) in str(current)
    if op == "ne":
        if current is None and body["value"] is None:
            return False
        if current is None or body["value"] is None:
            return True
        return not _same(current, _encode(body["value"], attr, "$"), attr)
    if current is None:
        return False
    expected = _encode(body["value"], attr, "$")
    if op == "eq":
        return _same(current, expected, attr)
    return _cmp(op, _as_comparable(current, attr), _as_comparable(expected, attr))


def _same(left: Any, right: Any, attr: AttrFact) -> bool:
    return _as_comparable(left, attr) == _as_comparable(right, attr)


def _as_comparable(value: Any, attr: AttrFact) -> Any:
    kind = attr.value_type()
    if kind in {"integer"} and not isinstance(value, bool):
        return int(value)
    if kind == "decimal":
        return Decimal(str(value))
    if kind == "number" and not isinstance(value, bool):
        return float(value)
    return value


def _cmp(op: str, left: Any, right: Any) -> bool:
    if op == "lt":
        return bool(left < right)
    if op == "lte":
        return bool(left <= right)
    if op == "gt":
        return bool(left > right)
    return bool(left >= right)


def _parse_duration(raw: Any, path: str, value_type: str) -> re.Match[str]:
    if not isinstance(raw, str):
        raise RuleProblem(path, "rel_time must be an ISO 8601 duration")
    match = _DURATION.fullmatch(raw)
    if match is None or not any(match.group(name) for name in ("y", "mo", "d", "h", "mi", "s")):
        raise RuleProblem(path, "rel_time must be an ISO 8601 duration")
    if value_type == "date" and any(match.group(name) for name in ("h", "mi", "s")):
        raise RuleProblem(path, "rel_time on a date cannot include a time")
    if "T" in raw and not any(match.group(name) for name in ("h", "mi", "s")):
        raise RuleProblem(path, "rel_time must be an ISO 8601 duration")
    return match


def _interval_sql(raw: str) -> str:
    match = _DURATION.fullmatch(raw)
    assert match is not None
    parts: list[str] = []
    for group, unit in (
        ("y", "years"),
        ("mo", "months"),
        ("d", "days"),
        ("h", "hours"),
        ("mi", "minutes"),
        ("s", "seconds"),
    ):
        number = match.group(group)
        if number is not None:
            parts.append(f"{number} {unit}")
    text = " ".join(parts) or "0 seconds"
    if match.group("sign"):
        text = f"-{text}"
    return f"INTERVAL '{text}'"


def _shift(now: datetime, raw: str) -> datetime:
    match = _DURATION.fullmatch(raw)
    assert match is not None
    sign = -1 if match.group("sign") else 1
    years = sign * int(match.group("y") or 0)
    months = sign * int(match.group("mo") or 0)
    days = sign * int(match.group("d") or 0)
    hours = sign * int(match.group("h") or 0)
    minutes = sign * int(match.group("mi") or 0)
    seconds = sign * Decimal(match.group("s") or 0)
    month_index = now.month - 1 + months
    year = now.year + years + month_index // 12
    month = month_index % 12 + 1
    day = min(now.day, _month_days(year, month))
    shifted = now.replace(year=year, month=month, day=day)
    whole = int(seconds)
    micros = int((seconds - whole) * 1_000_000)
    return shifted + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=whole, microseconds=micros
    )


def _month_days(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - timedelta(days=1)).day


def _literal(value: Any, attr: AttrFact) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _quote(value.astimezone(timezone.utc).isoformat())
    if isinstance(value, date):
        return _quote(value.isoformat())
    text = str(value)
    if attr.value_type() == "json":
        return f"{_quote(text)}::jsonb"
    return _quote(text)


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _quote(value: str) -> str:
    return "'" + _escape(value) + "'"


def _escape(value: str) -> str:
    return value.replace("'", "''")
