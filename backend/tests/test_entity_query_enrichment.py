"""Focused unit tests for enriched Entity Query compiler, Entity MCP sort,
Data Channel read.entity adapter, and Catalog Sample 4-dialect compiler.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.channel.graph import refine_ports, validate
from backend.channel.nodes.read.entity import NODE_TYPE as READ_ENTITY_NODE
from backend.channel.nodes.spec import ResolvedAttribute, ResolvedEntity
from backend.entity.data.filters import compile_filters
from backend.entity.data.head import HeadTarget
from backend.entity.errors import EntityRowInvalid
from backend.entity.records import (
    AttributeRecord,
    BusinessEntityRecord,
    EntityVersionRecord,
)
from backend.metadata.errors import SampleFilterInvalid
from backend.metadata.query.compile_sample import (
    SampleFilterSpec,
    compile_sample_sql,
)
from backend.metadata.query.guards import assert_readonly_single_statement
from backend.metadata.schemas.query import SampleFilterIn


def _target() -> HeadTarget:
    now = datetime.now(timezone.utc)
    attrs = [
        AttributeRecord(name="sku", type="string", required=True, unique=True, max_length=32),
        AttributeRecord(name="note", type="text"),
        AttributeRecord(name="qty", type="integer"),
        AttributeRecord(name="price", type="decimal", precision=10, scale=2),
        AttributeRecord(name="doc", type="json"),
        AttributeRecord(name="active", type="boolean"),
    ]
    entity = BusinessEntityRecord(
        id="ent_1",
        table_name="widget",
        name="Widget",
        description="",
        deprecated_at=None,
        created_at=now,
        updated_at=now,
    )
    version = EntityVersionRecord(
        id="ver_1",
        entity_id="ent_1",
        version=1,
        attributes=attrs,
        materialized_attributes=[],
        publish_status="published",
        latest_reconcile_job_id=None,
        created_at=now,
        updated_at=now,
    )
    return HeadTarget(
        entity=entity,
        head=version,
        attributes=attrs,
        physical_table="widget__v1",
        qualified_table='"entity_data"."widget__v1"',
        writable=True,
        read_relation='"entity_access"."widget_v"',
    )


def test_compile_filters_lowers_sugar_and_enforces_not_and_allowed_fields() -> None:
    target = _target()

    between = compile_filters(
        {"field": "sku", "op": "between", "value": ["A01", "A99"]}, target
    )
    assert between is not None
    assert between.leakproof is True
    assert '"sku" >=' in between.sql and '"sku" <=' in between.sql
    assert json.loads(between.profile_json) == {
        "all": [
            {"field": "sku", "op": "gte", "value": "A01"},
            {"field": "sku", "op": "lte", "value": "A99"},
        ]
    }

    not_in = compile_filters(
        {"field": "qty", "op": "not_in", "value": [1, 2]}, target
    )
    assert not_in is not None
    assert not_in.leakproof is True
    assert "IS NULL OR" in not_in.sql
    assert json.loads(not_in.profile_json) == {
        "any": [
            {"field": "qty", "op": "is_null"},
            {"not": {"field": "qty", "op": "in", "value": [1, 2]}},
        ]
    }

    not_contains = compile_filters(
        {"field": "sku", "op": "not_contains", "value": "100%"}, target
    )
    assert not_contains is not None
    assert not_contains.leakproof is False
    assert "IS NULL OR" in not_contains.sql
    assert "NOT ILIKE" in not_contains.sql

    negated = compile_filters(
        {"not": {"field": "active", "op": "eq", "value": True}}, target
    )
    assert negated is not None
    assert negated.leakproof is True
    assert "NOT COALESCE(" in negated.sql

    # JSONB operators
    for op, val, sql_frag in [
        ("json_contains", {"k": 1}, "@>"),
        ("has_key", "k", "?"),
        ("has_any_keys", ["a", "b"], "?|"),
        ("has_all_keys", ["a", "b"], "?&"),
    ]:
        compiled = compile_filters({"field": "doc", "op": op, "value": val}, target)
        assert compiled is not None
        assert compiled.leakproof is False
        assert sql_frag in compiled.sql

    # allowed_fields blocks withheld/hidden columns even inside `not`
    with pytest.raises(EntityRowInvalid, match="Unknown filter field 'qty'"):
        compile_filters(
            {"not": {"field": "qty", "op": "gte", "value": 5}},
            target,
            allowed_fields={"sku"},
        )
    with pytest.raises(EntityRowInvalid, match="Unknown filter field '__withheld'"):
        compile_filters(
            {"field": "__withheld", "op": "is_null"},
            target,
            allowed_fields={"sku"},
        )


def test_read_entity_node_refines_and_validates_operators() -> None:
    class Resolver:
        self_channel_id = "ch_self"

        def entity_head(self, entity_id: str) -> ResolvedEntity | None:
            if entity_id != "ent_1":
                return None
            return ResolvedEntity(
                attributes=(
                    ResolvedAttribute("sku", True, True, "string", ("eq", "gte", "contains")),
                    ResolvedAttribute("doc", False, False, "json", ("eq", "has_key"), sortable=False),
                )
            )

        def channel_exists(self, channel_id: str) -> bool:
            return False

        def published_trigger_type(self, channel_id: str) -> str | None:
            return None

        def published_subchannel_contract(self, channel_id: str):
            return None

        def source_exists(self, source_id: str) -> bool:
            return False

    graph = {
        "nodes": [
            {
                "id": "t1",
                "type": "trigger.manual",
                "type_version": 1,
                "name": "T",
                "ref": "t",
                "config": {},
            },
            {
                "id": "r1",
                "type": "read.entity",
                "type_version": 1,
                "name": "Read",
                "ref": "read",
                "config": {
                    "entity_id": "ent_1",
                    "match": "all",
                    "filters": [
                        {"attribute": "sku", "op": "gte", "value": "A"},
                        {"attribute": "row_id", "op": "is_not_null"},
                    ],
                    "sort_attribute": "sku",
                    "sort_direction": "asc",
                    "limit": 100,
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": {"node_id": "t1", "port": "main"},
                "target": {"node_id": "r1", "port": "main"},
            }
        ],
        "settings": {},
    }
    assert validate(graph, Resolver()) == []
    ports = refine_ports(graph, Resolver())
    r1_out = next(p for p in ports if p.node_id == "r1" and p.port == "main" and p.direction == "output")
    assert r1_out.schema["properties"]["rows"]["items"]["properties"]["row_id"] == {"type": "integer"}
    assert r1_out.schema["properties"]["rows"]["items"]["properties"]["sku"] == {"type": ["string", "null"]}

    # Invalid operator for attribute + non-sortable json sort_attribute
    bad_graph = {
        "nodes": [
            {
                "id": "t1",
                "type": "trigger.manual",
                "type_version": 1,
                "name": "T",
                "ref": "t",
                "config": {},
            },
            {
                "id": "r1",
                "type": "read.entity",
                "type_version": 1,
                "name": "Read",
                "ref": "read",
                "config": {
                    "entity_id": "ent_1",
                    "filters": [{"attribute": "doc", "op": "gte", "value": "1"}],
                    "sort_attribute": "doc",
                },
            },
        ],
        "edges": [
            {
                "id": "e1",
                "source": {"node_id": "t1", "port": "main"},
                "target": {"node_id": "r1", "port": "main"},
            }
        ],
        "settings": {},
    }
    problems = validate(bad_graph, Resolver())
    assert any("not allowed" in p.detail for p in problems)
    assert any("Sorting is not supported" in p.detail for p in problems)
    assert READ_ENTITY_NODE.type_id == "read.entity"


def test_catalog_sample_enriched_operators_and_dialects() -> None:
    assert SampleFilterIn(column="status", op="neq", value="x").op == "ne"

    for engine in ("postgresql", "mysql", "mssql", "oracle"):
        sql = compile_sample_sql(
            engine=engine,
            schema_name="public",
            object_name="orders",
            known_columns={"id", "status"},
            columns=None,
            match="any",
            column_types={"id": "integer", "status": "text"},
            filters=[
                SampleFilterSpec("id", "gte", "10"),
                SampleFilterSpec("id", "between", ["1", "100"]),
                SampleFilterSpec("status", "not_in", ["closed", "void"]),
                SampleFilterSpec("status", "starts_with", "op_"),
                SampleFilterSpec("status", "not_contains", "test"),
                SampleFilterSpec("status", "is_not_null", ""),
            ],
            order_by=[],
            offset=0,
            limit=20,
        )
        assert_readonly_single_statement(sql, engine=engine)
        assert "10" in sql

    with pytest.raises(SampleFilterInvalid, match="Invalid numeric"):
        compile_sample_sql(
            engine="postgresql",
            schema_name="public",
            object_name="orders",
            known_columns={"id"},
            columns=None,
            column_types={"id": "integer"},
            filters=[SampleFilterSpec("id", "gte", "not-a-number")],
            order_by=[],
            offset=0,
            limit=10,
        )
