"""Template fields: static text, one expression, and concatenation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.channel.template import (
    TemplateSyntaxError,
    TemplateTypeError,
    output_matches,
    parse,
    render,
    schema_at_path,
    static_check,
)
from backend.channel.values import LIST_OF_OBJECTS

STRING = {"type": "string"}
INTEGER = {"type": "integer"}


def _eval(body: str) -> object:
    return eval(body, {"__builtins__": {}}, {})  # noqa: S307


def test_static_json_list_needs_no_braces() -> None:
    text = '[{"sku": "BT-abc", "qty": 8}]'
    template = parse(text)
    assert template.whole_expression is None
    assert static_check(template, LIST_OF_OBJECTS) == "ok"
    assert render(text, _eval, LIST_OF_OBJECTS) == [{"sku": "BT-abc", "qty": 8}]


def test_single_expression_keeps_a_native_list() -> None:
    text = '{{ [{"sku": "BT-abc", "qty": 8}] }}'
    template = parse(text)
    assert template.whole_expression == '[{"sku": "BT-abc", "qty": 8}]'
    assert static_check(template, LIST_OF_OBJECTS) == "unknown"
    assert render(text, _eval, LIST_OF_OBJECTS) == [{"sku": "BT-abc", "qty": 8}]


def test_concatenation_into_a_list_waits_until_run_time() -> None:
    template = parse('[{"sku": "{{ 1 }}"}]')
    assert template.whole_expression is None
    assert static_check(template, LIST_OF_OBJECTS) == "unknown"
    assert render('[{"sku": "{{ 1 }}"}]', _eval, LIST_OF_OBJECTS) == [{"sku": "1"}]


def test_concatenation_builds_a_string() -> None:
    text = 'abc{{ "def" }}'
    assert render(text, _eval, STRING) == "abcdef"


def test_concatenation_turns_none_into_an_empty_string() -> None:
    assert render("a{{ None }}b", _eval, STRING) == "ab"


def test_bare_none_is_not_a_string() -> None:
    with pytest.raises(TemplateTypeError):
        render("{{ None }}", _eval, STRING)


def test_escaped_braces_are_literal_text() -> None:
    assert parse(r"\{{ not code }}").whole_expression is None
    assert render(r"\{{ not code }}", _eval, STRING) == "{{ not code }}"


def test_static_text_that_is_not_the_declared_type_fails() -> None:
    template = parse("not-json")
    with pytest.raises(TemplateTypeError):
        static_check(template, LIST_OF_OBJECTS)


def test_integer_text_parses_once_as_json() -> None:
    assert render("8", _eval, INTEGER) == 8


def test_native_string_is_not_an_integer() -> None:
    with pytest.raises(TemplateTypeError):
        render('{{ "8" }}', _eval, INTEGER)


def test_unclosed_expression_does_not_parse() -> None:
    with pytest.raises(TemplateSyntaxError):
        parse("{{ 1")


def test_expression_refs_are_collected() -> None:
    template = parse('{{ self.read.output.rows }}')
    assert template.refs == frozenset({"read"})
    named = parse('{{ self.nodes["Read suppliers"].output }}')
    assert named.node_names == frozenset({"Read suppliers"})


def test_context_reads_are_collected_apart_from_refs() -> None:
    template = parse("{{ self.run.id }}-{{ self.platform.now }}-{{ self.read.output }}")
    assert template.contexts == frozenset({"run", "platform"})
    assert template.refs == frozenset({"read"})


def test_string_target_serializes_objects() -> None:
    assert render('{{ {"n": 1} }}', _eval, STRING) == '{"n": 1}'


_ROWS = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "qty": {"type": "integer"},
                },
            },
        },
        "count": {"type": "integer"},
    },
}


def test_static_path_reads_attributes_and_constant_indexes() -> None:
    upstream = {"read": {"main": _ROWS}}
    assert schema_at_path("{{ self.read.output.rows[0].code }}", upstream) == {"type": "string"}
    assert schema_at_path('{{ self.read.output["rows"][0]["qty"] }}', upstream) == {
        "type": "integer"
    }
    assert schema_at_path("{{ self.read.output.rows[0] }}", upstream) == _ROWS["properties"]["rows"][
        "items"
    ]
    assert schema_at_path("{{ self.read.output }}", upstream) == _ROWS
    named = schema_at_path(
        '{{ self.nodes["Read suppliers"].output.count }}',
        upstream,
        {"Read suppliers": "read"},
    )
    assert named == {"type": "integer"}


def test_static_path_that_is_not_a_pure_chain_has_no_schema() -> None:
    upstream = {"read": {"main": _ROWS}}
    assert schema_at_path("{{ self.read.output.missing }}", upstream) is None
    assert schema_at_path("{{ self.read.output.rows[index] }}", upstream) is None
    assert schema_at_path("{{ self.read.output.rows + [] }}", upstream) is None
    assert schema_at_path("{{ self.channel.id }}", upstream) is None
    assert schema_at_path("{{ self.nodes[name].output }}", upstream, {"name": "read"}) is None
    assert schema_at_path('prefix {{ self.read.output.rows }}', upstream) is None
    assert schema_at_path("not a template", upstream) is None
    assert schema_at_path("{{ self.other.output.rows }}", upstream) is None
    assert (
        schema_at_path('{{ self.nodes["Read suppliers"].output }}', upstream, {}) is None
    )


def test_static_path_reads_the_stored_output_unless_inside_the_frame() -> None:
    step = {
        "type": "object",
        "properties": {
            "current": {"type": "string"},
            "rows": {"type": "array", "items": {"type": "object"}},
        },
    }
    stored = {
        "type": "object",
        "properties": {
            "current": {"type": ["string", "null"]},
            "iterations": {"type": "array"},
        },
    }
    upstream = {"loop": {"each": step, "done": stored}}
    assert schema_at_path("{{ self.loop.output.current }}", upstream) == {
        "type": ["string", "null"]
    }
    assert schema_at_path("{{ self.loop.output.iterations }}", upstream) == {"type": "array"}
    assert schema_at_path("{{ self.loop.output.rows }}", upstream) is None

    assert schema_at_path(
        "{{ self.loop.output.rows[0] }}", upstream, inside=frozenset({"loop"})
    ) == {"type": "object"}
    assert (
        schema_at_path("{{ self.loop.output.iterations }}", upstream, inside=frozenset({"loop"}))
        is None
    )


def test_schema_without_a_type_matches_any_json_value() -> None:
    assert output_matches("x", {})
    assert output_matches(None, {})
    assert output_matches([1], {})
    declared = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"label": {"type": "string"}, "expr": {}},
        "required": ["label", "expr"],
    }
    assert output_matches({"label": "ok", "expr": "1 + 1"}, declared)
    assert output_matches({"label": "ok", "expr": {"n": 1}}, declared)
    assert output_matches({"sku": "BT"}, {"type": "object"})


def test_datetime_in_a_concatenation_is_iso() -> None:
    instant = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    def evaluate(body: str) -> object:
        del body
        return instant

    assert render("at {{ 1 }}", evaluate, STRING) == "at 2026-10-11T12:00:00+00:00"
