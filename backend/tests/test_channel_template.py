"""Template fields: static text, one expression, and concatenation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.channel.template import (
    TemplateSyntaxError,
    TemplateTypeError,
    parse,
    render,
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


def test_string_target_serializes_objects() -> None:
    assert render('{{ {"n": 1} }}', _eval, STRING) == '{"n": 1}'


def test_datetime_in_a_concatenation_is_iso() -> None:
    instant = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)

    def evaluate(body: str) -> object:
        del body
        return instant

    assert render("at {{ 1 }}", evaluate, STRING) == "at 2026-10-11T12:00:00+00:00"
