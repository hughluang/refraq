"""Catalog rules for Data Channel node types.

Every registered type states its function, documents its ports and configuration
fields, and lives in exactly one family module that exports ``NODE_TYPE``.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest

from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import NodeType, PortSpec

_PORT_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
_SUMMARY_MAX = 160
_NODES_ROOT = Path(__file__).resolve().parents[1] / "channel" / "nodes"


def test_every_type_states_its_function_and_ports() -> None:
    types = list_node_types()
    assert types
    assert len({item.type_id for item in types}) == len(types)
    for node in types:
        assert node.label.strip()
        assert _sentence_count(node.summary) == 1
        assert len(node.summary) <= _SUMMARY_MAX
        assert _sentence_count(node.description) >= 2
        assert node.type_version >= 1
        for port in (*node.inputs, *node.outputs):
            assert _PORT_NAME.fullmatch(port.port), port.port
            assert port.description.strip()
            assert port.coarse_type in {"object", "items", "unknown"}
        assert all(port.port != "error" for port in node.inputs)
        error_ports = [port for port in node.outputs if port.port == "error"]
        assert len(error_ports) <= 1
        for port in error_ports:
            assert port.loop_back is False
            assert "error_output" in port.description
        _assert_property_docs(node.config_schema)


def test_every_registered_type_has_execute() -> None:
    types = list_node_types()
    assert types
    for node in types:
        assert callable(node.execute)


def test_a_node_type_requires_execute() -> None:
    with pytest.raises(TypeError):
        NodeType(
            type_id="test.bare",
            family="test",
            label="Bare",
            summary="Has no execute function.",
            description="Test type. Constructing it without execute fails.",
            trigger=False,
            inputs=(),
            outputs=(PortSpec("main", "Output."),),
            config_schema={"type": "object"},
        )


def test_every_node_module_is_registered_and_exports_only_node_type() -> None:
    registered = {item.type_id: item for item in list_node_types()}
    found: dict[str, NodeType] = {}
    for family_dir in sorted(path for path in _NODES_ROOT.iterdir() if path.is_dir()):
        if family_dir.name.startswith("_"):
            continue
        for module_path in sorted(family_dir.glob("*.py")):
            if module_path.name == "__init__.py":
                continue
            module_name = f"backend.channel.nodes.{family_dir.name}.{module_path.stem}"
            module = importlib.import_module(module_name)
            assert module.__all__ == ["NODE_TYPE"]
            doc = (module.__doc__ or "").strip()
            assert doc
            assert "\n" not in doc
            node = module.NODE_TYPE
            assert isinstance(node, NodeType)
            assert node.family == family_dir.name
            assert node.type_id == f"{family_dir.name}.{module_path.stem}"
            found[node.type_id] = node
    assert found.keys() == registered.keys()
    for type_id, node in found.items():
        assert registered[type_id] is node


def test_batch_read_is_registered_as_a_container() -> None:
    from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA
    from backend.channel.item_limit import ITEM_LIMIT

    node = next(item for item in list_node_types() if item.type_id == "volume.batch_read")
    assert [port.port for port in node.inputs] == ["main"]
    assert [port.port for port in node.outputs] == ["each", "done"]
    assert all(port.loop_back is False for port in node.outputs)
    schema = node.config_schema
    assert schema["required"] == ["dataset"]
    dataset = schema["properties"]["dataset"]
    assert dataset["type"] == "string"
    assert dataset["x-refraq-template"] is DATASET_REFERENCE_SCHEMA
    size = schema["properties"]["batch_size"]
    assert size["type"] == "integer"
    assert size["minimum"] == 1
    assert size["maximum"] == ITEM_LIMIT
    assert size["default"] == 1000
    assert "batch_size" not in schema["required"]


def test_dataset_query_and_materialize_are_registered() -> None:
    types = {item.type_id: item for item in list_node_types()}
    query = types["volume.dataset_query"]
    materialize = types["volume.materialize"]
    sql = types["read.sql"]
    timeout = query.config_schema["properties"]["statement_timeout_sec"]
    assert timeout["type"] == "integer"
    assert timeout["minimum"] == 1
    assert timeout["maximum"] == 3600
    assert timeout["default"] == 300
    assert "statement_timeout_sec" not in query.config_schema["required"]
    assert query.config_schema["properties"]["source"]["properties"]["kind"]["enum"] == (
        sql.config_schema["properties"]["source"]["properties"]["kind"]["enum"]
    )
    assert query.config_schema["properties"]["sql"]["x-refraq-template"] == {"type": "string"}
    assert set(query.config_schema["required"]) == {"source", "sql"}
    assert materialize.config_schema["required"] == ["items"]
    assert materialize.config_schema["properties"]["items"]["x-refraq-template"]["type"] == "array"
    assert [port.port for port in query.outputs] == ["main", "error"]
    assert [port.port for port in materialize.outputs] == ["main", "error"]


def _sentence_count(text: str) -> int:
    return len([part for part in re.split(r"[.?!]", text.strip()) if part.strip()])


def _assert_property_docs(schema: dict[str, Any]) -> None:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return
    for name, prop in properties.items():
        assert isinstance(prop, dict), name
        title = prop.get("title")
        description = prop.get("description")
        assert isinstance(title, str) and title.strip(), name
        assert isinstance(description, str) and description.strip(), name
        _assert_property_docs(prop)
        items = prop.get("items")
        if isinstance(items, dict):
            _assert_property_docs(items)
