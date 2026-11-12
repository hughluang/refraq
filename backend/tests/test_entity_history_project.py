"""Projection sends one JSON payload instead of one bind per cell."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.entity.access.facts import AttrFact
from backend.entity.history.project import _Candidate, _json_param, _query


@dataclass
class _Policy:
    source_sql: str
    attributes: tuple[AttrFact, ...]
    subject_values: dict
    now: datetime


class _Conn:
    def __init__(self) -> None:
        self.params = None

    def exec_driver_sql(self, sql: str) -> None:
        del sql

    def execute(self, statement, params):
        del statement
        self.params = params
        return self

    def mappings(self):
        return []


def test_json_param_keeps_decimal_and_instant_precision() -> None:
    assert _json_param(Decimal("1.20")) == "1.20"
    instant = datetime(2026, 11, 12, 4, 28, 1, 123456, tzinfo=timezone.utc)
    assert _json_param(instant) == "2026-11-12T04:28:01.123456Z"


def test_json_param_rejects_an_unknown_object() -> None:
    with pytest.raises(TypeError, match="cannot encode"):
        _json_param(object())


def test_query_binds_a_wide_page_as_one_payload(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def render(shape, policy, **kwargs):
        del shape, kwargs
        seen["source"] = policy.source_sql
        return "SELECT 1"

    monkeypatch.setattr("backend.entity.history.project.render_shape", render)
    attributes = tuple(
        AttrFact(attribute_id=f"a{index}", name=f"a{index}", type="string")
        for index in range(55)
    )
    policy = _Policy(
        source_sql="",
        attributes=attributes,
        subject_values={},
        now=datetime(2026, 11, 12, tzinfo=timezone.utc),
    )
    conn = _Conn()
    count = 3000
    candidates = [
        _Candidate(
            key=str(index),
            row_id=index,
            values={"a0": Decimal("10.50")} if index == 0 else {},
            present=frozenset(),
        )
        for index in range(count)
    ]
    found = _query(
        conn,
        candidates,
        policy,
        SimpleNamespace(shape=object()),
        SimpleNamespace(user_id="u"),
    )
    assert found == {}
    assert list(conn.params) == ["payload"]
    assert "jsonb_to_recordset" in seen["source"]
    assert "VALUES" not in seen["source"]
    rows = json.loads(conn.params["payload"])
    assert len(rows) == count
    assert rows[0]["a0"] == "10.50"
    assert rows[0]["row_id"] == "0"
    assert rows[1]["a0"] is None
