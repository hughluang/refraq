"""Template fields: text, with {{ }} marking a Python expression."""

from __future__ import annotations

import ast
import copy
import json
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Callable, Literal, Mapping

from backend.channel.values import array_item_schema

__all__ = [
    "Template",
    "TemplateSyntaxError",
    "TemplateTypeError",
    "output_matches",
    "parse",
    "render",
    "schema_at_path",
    "static_check",
    "value_matches",
]

_CONTEXT_ATTRS = frozenset({"channel", "run", "platform"})
_RESERVED_ATTRS = _CONTEXT_ATTRS | {"nodes"}


class TemplateSyntaxError(ValueError):
    """The template text is not a well-formed template."""


class TemplateTypeError(ValueError):
    """A template result does not match its declared value type."""


@dataclass(frozen=True, slots=True)
class Segment:
    kind: Literal["text", "expr"]
    text: str


@dataclass(frozen=True, slots=True)
class Template:
    raw: str
    segments: tuple[Segment, ...]
    whole_expression: str | None
    refs: frozenset[str]
    node_names: frozenset[str]
    contexts: frozenset[str]


def parse(text: str) -> Template:
    """Split template text. Leading and trailing whitespace is ignored."""
    raw = text.strip()
    segments = tuple(_scan(raw))
    whole = (
        segments[0].text if len(segments) == 1 and segments[0].kind == "expr" else None
    )
    refs: set[str] = set()
    names: set[str] = set()
    contexts: set[str] = set()
    for segment in segments:
        if segment.kind != "expr":
            continue
        found_refs, found_names, found_contexts = _names(segment.text)
        refs.update(found_refs)
        names.update(found_names)
        contexts.update(found_contexts)
    return Template(
        raw=raw,
        segments=segments,
        whole_expression=whole,
        refs=frozenset(refs),
        node_names=frozenset(names),
        contexts=frozenset(contexts),
    )


def schema_at_path(
    text: str,
    upstream: Mapping[str, Any],
    names: Mapping[str, str] | None = None,
    *,
    inside: set[str] | frozenset[str] | None = None,
) -> dict[str, Any] | None:
    """Schema at one pure attribute path, or None when the path cannot be typed.

    The text must be exactly one ``{{ }}``. The expression may only be
    attributes and constant subscripts, rooted at ``self.<ref>.output`` or
    ``self.nodes["name"].output``. ``names`` maps a node name to its ref.
    An integer subscript selects that array's ``items`` schema. ``upstream``
    is keyed by ref and each value is that node's port schemas. ``.output``
    is ``main`` when that port has a schema, otherwise the stored ``done``
    schema, then the round step ``each``. A ref in ``inside``, or on
    ``upstream.inside``, is read as the round step instead.
    """
    try:
        template = parse(text)
    except TemplateSyntaxError:
        return None
    if template.whole_expression is None:
        return None
    steps = _path_steps(template.whole_expression)
    if not steps:
        return None
    if names is None:
        attached = getattr(upstream, "names", None)
        names = attached if isinstance(attached, Mapping) else {}
    if inside is None:
        attached_inside = getattr(upstream, "inside", ())
        inside = attached_inside if isinstance(attached_inside, (set, frozenset)) else frozenset()
    found = _schema_from_steps(steps, upstream, names, inside)
    if not isinstance(found, dict):
        return None
    return copy.deepcopy(found)


def static_check(
    template: Template, value_schema: Mapping[str, Any] | None
) -> Literal["ok", "unknown"]:
    """Check a template without running it.

    A missing schema, a single expression, or concatenation into a non-string
    type is unknown until run time. Text with no expression is checked now.
    """
    if value_schema is None:
        return "unknown"
    if template.whole_expression is not None:
        return "unknown"
    if any(segment.kind == "expr" for segment in template.segments):
        if _is_string(value_schema):
            return "ok"
        return "unknown"
    _coerce_text(_joined_text(template), value_schema)
    return "ok"


def render(
    text: str,
    evaluate: Callable[[str], Any],
    value_schema: Mapping[str, Any],
) -> Any:
    """Evaluate a template and convert the result to the declared type."""
    template = parse(text)
    if template.whole_expression is not None:
        return _coerce_native(evaluate(template.whole_expression), value_schema)
    parts: list[str] = []
    for segment in template.segments:
        if segment.kind == "text":
            parts.append(segment.text)
        else:
            parts.append(_to_text(evaluate(segment.text)))
    return _coerce_text("".join(parts), value_schema)


def value_matches(value: Any, schema: Mapping[str, Any]) -> bool:
    return _matches(value, schema, widen=False)


def output_matches(value: Any, schema: Mapping[str, Any]) -> bool:
    """Match a node output. Dates and decimals count as their JSON types."""
    return _matches(value, schema, widen=True)


def _scan(text: str) -> list[Segment]:
    segments: list[Segment] = []
    buf: list[str] = []
    index = 0
    length = len(text)

    def flush() -> None:
        if buf:
            segments.append(Segment("text", "".join(buf)))
            buf.clear()

    while index < length:
        if text[index] == "\\":
            end = index
            while end < length and text[end] == "\\":
                end += 1
            count = end - index
            if text.startswith("{{", end):
                buf.append("\\" * (count // 2))
                if count % 2 == 1:
                    buf.append("{{")
                    index = end + 2
                    continue
                index = end
                continue
            buf.append("\\" * count)
            index = end
            continue
        if text.startswith("{{", index):
            flush()
            body, index = _read_expression(text, index + 2)
            segments.append(Segment("expr", body))
            continue
        buf.append(text[index])
        index += 1
    flush()
    return segments


def _read_expression(text: str, start: int) -> tuple[str, int]:
    index = start
    length = len(text)
    depth = 0
    quote: str | None = None
    while index < length:
        char = text[index]
        if quote is not None:
            if char == "\\" and len(quote) == 1:
                index += 2
                continue
            if text.startswith(quote, index):
                index += len(quote)
                quote = None
                continue
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char * 3 if text.startswith(char * 3, index) else char
            index += len(quote)
            continue
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            if depth > 0:
                depth -= 1
                index += 1
                continue
            if index + 1 < length and text[index + 1] == "}":
                body = text[start:index].strip()
                if not body:
                    raise TemplateSyntaxError("Expression is empty")
                try:
                    ast.parse(body, mode="eval")
                except SyntaxError as exc:
                    raise TemplateSyntaxError("Expression does not parse") from exc
                return body, index + 2
            raise TemplateSyntaxError("Expression has an unmatched brace")
        index += 1
    raise TemplateSyntaxError("Expression is not closed")


def _names(body: str) -> tuple[set[str], set[str], set[str]]:
    tree = ast.parse(body, mode="eval")
    refs: set[str] = set()
    names: set[str] = set()
    contexts: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_Attribute(self, node: ast.Attribute) -> None:
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                if node.attr in _CONTEXT_ATTRS:
                    contexts.add(node.attr)
                elif node.attr not in _RESERVED_ATTRS:
                    refs.add(node.attr)
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript) -> None:
            value = node.value
            key = node.slice
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id == "self"
                and value.attr == "nodes"
                and isinstance(key, ast.Constant)
                and isinstance(key.value, str)
            ):
                names.add(key.value)
            self.generic_visit(node)

    Visitor().visit(tree)
    return refs, names, contexts


def _path_steps(expression: str) -> list[tuple[str, Any]] | None:
    node: ast.AST = ast.parse(expression, mode="eval").body
    steps: list[tuple[str, Any]] = []
    while True:
        if isinstance(node, ast.Attribute):
            steps.append(("attr", node.attr))
            node = node.value
            continue
        if isinstance(node, ast.Subscript):
            key = _subscript_key(node.slice)
            if key is None:
                return None
            steps.append(("key", key))
            node = node.value
            continue
        if isinstance(node, ast.Name) and node.id == "self":
            break
        return None
    steps.reverse()
    return steps


def _subscript_key(node: ast.expr) -> str | int | None:
    if isinstance(node, ast.Constant):
        return _const_key(node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
    ):
        key = _const_key(node.operand.value)
        if isinstance(key, int):
            return -key
    return None


def _const_key(value: object) -> str | int | None:
    if isinstance(value, str):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _schema_from_steps(
    steps: list[tuple[str, Any]],
    upstream: Mapping[str, Any],
    names: Mapping[str, str],
    inside: set[str] | frozenset[str],
) -> dict[str, Any] | None:
    if steps[0][0] != "attr":
        return None
    first = steps[0][1]
    index = 1
    if first == "nodes":
        if len(steps) < 2 or steps[1][0] != "key" or not isinstance(steps[1][1], str):
            return None
        ref = names.get(steps[1][1])
        if not isinstance(ref, str):
            return None
        index = 2
    elif first in _RESERVED_ATTRS:
        return None
    else:
        ref = first
    if index >= len(steps) or steps[index] != ("attr", "output"):
        return None
    produced = upstream.get(ref) if isinstance(upstream, Mapping) else None
    schema = _output_schema(produced, step=ref in inside)
    if schema is None:
        return None
    for kind, key in steps[index + 1 :]:
        schema = _walk_schema(schema, kind, key)
        if schema is None:
            return None
    return schema


def _output_schema(produced: Any, *, step: bool) -> dict[str, Any] | None:
    if not isinstance(produced, Mapping):
        return None
    ports = ("each", "main", "done", "true") if step else ("main", "done", "each", "true")
    for port in ports:
        schema = produced.get(port)
        if isinstance(schema, dict):
            return schema
    return None


def _walk_schema(schema: Any, kind: str, key: Any) -> dict[str, Any] | None:
    if not isinstance(schema, dict):
        return None
    if kind == "attr" or isinstance(key, str):
        return _property_schema(schema, key if isinstance(key, str) else "")
    return array_item_schema(schema)


def _property_schema(schema: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        found = properties.get(name)
        if isinstance(found, dict):
            return found
    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        return additional
    return None


def _joined_text(template: Template) -> str:
    return "".join(
        segment.text for segment in template.segments if segment.kind == "text"
    )


def _is_string(schema: Mapping[str, Any]) -> bool:
    return _type_names(schema) - {"null"} == {"string"}


def _coerce_native(value: Any, schema: Mapping[str, Any]) -> Any:
    if _is_string(schema):
        if value is None:
            if "null" in _type_names(schema):
                return None
            raise TemplateTypeError("None is not a string")
        if isinstance(value, str):
            return value
        return _to_text(value)
    if value_matches(value, schema):
        return value
    raise TemplateTypeError("Value does not match the declared type")


def _coerce_text(text: str, schema: Mapping[str, Any]) -> Any:
    if _is_string(schema):
        return text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TemplateTypeError("Value is not JSON of the declared type") from exc
    if value_matches(parsed, schema):
        return parsed
    raise TemplateTypeError("Value does not match the declared type")


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    raise TemplateTypeError("Value cannot be concatenated")


def _type_names(schema: Mapping[str, Any]) -> set[str]:
    kind = schema.get("type")
    if isinstance(kind, str):
        return {kind}
    if isinstance(kind, list):
        return {item for item in kind if isinstance(item, str)}
    return set()


def _matches(value: Any, schema: Mapping[str, Any], *, widen: bool) -> bool:
    if "enum" in schema and value not in schema["enum"]:
        return False
    names = _type_names(schema)
    if not names:
        # A schema that states no type, including {}, matches any JSON value.
        # An enum without a type still matches nothing.
        return "enum" not in schema
    return any(_matches_type(value, name, schema, widen=widen) for name in names)


def _matches_type(
    value: Any, name: str, schema: Mapping[str, Any], *, widen: bool
) -> bool:
    if name == "null":
        return value is None
    if name == "string":
        if isinstance(value, str):
            return True
        return widen and isinstance(value, (date, datetime, time))
    if name == "boolean":
        return isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return True
        return widen and isinstance(value, Decimal)
    if name == "array":
        if not isinstance(value, list):
            return False
        items = schema.get("items")
        if isinstance(items, dict):
            return all(_matches(item, items, widen=widen) for item in value)
        return True
    if name == "object":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties")
        required = schema.get("required")
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    return False
        if isinstance(properties, dict):
            for key, subschema in properties.items():
                if key in value and isinstance(subschema, dict):
                    if not _matches(value[key], subschema, widen=widen):
                        return False
        if schema.get("additionalProperties") is False and isinstance(properties, dict):
            return set(value).issubset(properties)
        return True
    return False
