"""Catalog rules for Data Channel node types.

Every registered type states its function, documents its ports and configuration
fields, and lives in exactly one family module that exports ``NODE_TYPE``.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import NodeType

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
