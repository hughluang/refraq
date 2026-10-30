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
from backend.channel.nodes.spec import ContainerSpec, NodeResult, NodeType, OutputView, PortSpec

_PORT_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
_SUMMARY_MAX = 160
_NODES_ROOT = Path(__file__).resolve().parents[1] / "channel" / "nodes"

# Literals from the output-view contract, not derived from the node modules.
_OUTPUT_VIEWS = {
    "trigger.error": OutputView(kind="record"),
    "trigger.manual": OutputView(kind="record"),
    "trigger.scheduled": OutputView(kind="record"),
    "read.changes": OutputView(
        kind="rows", rows="entries", metrics=("count", "has_more")
    ),
    "read.source_query": OutputView(
        kind="rows", rows="rows", metrics=("count", "truncated")
    ),
    "read.sql": OutputView(kind="rows", rows="rows", metrics=("count", "rowcount")),
    "transform.code": OutputView(kind="value"),
    "transform.deduplicate": OutputView(
        kind="rows", rows="rows", metrics=("count", "removed")
    ),
    "transform.filter": OutputView(
        kind="rows", rows="rows", metrics=("count", "dropped")
    ),
    "transform.if": OutputView(kind="record"),
    "transform.merge": OutputView(kind="rows", rows="rows", metrics=("count",)),
    "transform.set_fields": OutputView(kind="record"),
    "volume.batch_read": OutputView(
        kind="container", metrics=("count", "total", "batch_size"), item="rows"
    ),
    "volume.dataset_query": OutputView(
        kind="dataset", dataset="dataset", metrics=("count",)
    ),
    "volume.for": OutputView(kind="container", metrics=("count",), item="current"),
    "volume.materialize": OutputView(
        kind="dataset", dataset="dataset", metrics=("count",)
    ),
    "volume.until": OutputView(kind="container", metrics=("count",), item="index"),
    "state.variable": OutputView(kind="record"),
    "write.entity": OutputView(
        kind="counts",
        metrics=("inserted", "updated", "unchanged", "deleted", "unmatched"),
    ),
    "action.email": OutputView(kind="record"),
    "action.http": OutputView(kind="record"),
    "action.webhook": OutputView(kind="record"),
}


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
            assert "error_output" in port.description
        _assert_property_docs(node.config_schema)


def test_every_registered_type_has_execute_or_container() -> None:
    types = list_node_types()
    assert types
    for node in types:
        assert (node.execute is None) != (node.container is None)


def test_a_node_type_has_execute_or_container() -> None:
    def run_node(node: dict, hooks: object) -> NodeResult:
        del node, hooks
        return NodeResult(status="succeeded")

    def run_container(node: dict, hooks: object, body: object) -> NodeResult:
        del node, hooks, body
        return NodeResult(status="succeeded")

    bare = dict(
        type_id="test.bare",
        family="test",
        label="Bare",
        summary="Has neither execute nor container.",
        description="Test type. Constructing it with neither execute nor container fails.",
        trigger=False,
        inputs=(),
        outputs=(PortSpec("main", "Output."),),
        config_schema={"type": "object"},
        output_view=OutputView(kind="value"),
    )
    with pytest.raises(TypeError):
        NodeType(**bare)
    with pytest.raises(TypeError):
        NodeType(
            **bare,
            execute=run_node,
            container=ContainerSpec(run=run_container),
        )
    container = NodeType(**bare, container=ContainerSpec(run=run_container))
    assert container.execute is None
    assert container.container is not None
    assert container.container.round_templates == ()


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


def test_until_is_registered_as_a_container() -> None:
    from backend.channel.item_limit import ITEM_LIMIT

    node = next(item for item in list_node_types() if item.type_id == "volume.until")
    assert [port.port for port in node.inputs] == ["main"]
    assert [port.port for port in node.outputs] == ["each", "done"]
    assert node.output_view == OutputView(
        kind="container", metrics=("count",), item="index"
    )
    schema = node.config_schema
    assert schema["required"] == ["until", "max_iterations"]
    until = schema["properties"]["until"]
    assert until["type"] == "string"
    assert until["x-refraq-template"] == {"type": "boolean"}
    assert "default" not in until
    cap = schema["properties"]["max_iterations"]
    assert cap["type"] == "integer"
    assert cap["minimum"] == 1
    assert cap["maximum"] == ITEM_LIMIT
    assert "default" not in cap
    assert node.execute is None
    assert node.container is not None
    assert node.container.round_templates == ("until",)


def test_batch_read_is_registered_as_a_container() -> None:
    from backend.channel.dataset_ref import DATASET_REFERENCE_SCHEMA
    from backend.channel.item_limit import ITEM_LIMIT

    node = next(
        item for item in list_node_types() if item.type_id == "volume.batch_read"
    )
    assert [port.port for port in node.inputs] == ["main"]
    assert [port.port for port in node.outputs] == ["each", "done"]
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
    assert (
        query.config_schema["properties"]["source"]["properties"]["kind"]["enum"]
        == (sql.config_schema["properties"]["source"]["properties"]["kind"]["enum"])
    )
    assert query.config_schema["properties"]["sql"]["x-refraq-template"] == {
        "type": "string"
    }
    assert set(query.config_schema["required"]) == {"source", "sql"}
    assert materialize.config_schema["required"] == ["items"]
    assert (
        materialize.config_schema["properties"]["items"]["x-refraq-template"]["type"]
        == "array"
    )
    assert [port.port for port in query.outputs] == ["main", "error"]
    assert [port.port for port in materialize.outputs] == ["main", "error"]


def test_output_view_accepts_only_the_key_its_kind_names() -> None:
    OutputView(kind="record")
    OutputView(kind="value")
    OutputView(kind="counts", metrics=("inserted",))
    OutputView(kind="container", item="current", metrics=("count",))
    OutputView(kind="rows", rows="rows", metrics=("count", "rowcount"))
    OutputView(kind="dataset", dataset="dataset", metrics=("count",))
    with pytest.raises(ValueError):
        OutputView(kind="rows")
    with pytest.raises(ValueError):
        OutputView(kind="rows", rows="")
    with pytest.raises(ValueError):
        OutputView(kind="dataset")
    with pytest.raises(ValueError):
        OutputView(kind="dataset", dataset="")
    with pytest.raises(ValueError):
        OutputView(kind="record", rows="rows")
    with pytest.raises(ValueError):
        OutputView(kind="record", dataset="dataset")
    with pytest.raises(ValueError):
        OutputView(kind="rows", rows="rows", dataset="dataset")
    with pytest.raises(ValueError):
        OutputView(kind="dataset", dataset="dataset", rows="rows")
    with pytest.raises(ValueError):
        OutputView(kind="counts", rows="rows", metrics=("inserted",))
    with pytest.raises(ValueError):
        OutputView(kind="nope")
    with pytest.raises(ValueError):
        OutputView(kind="container", metrics=("count",))
    with pytest.raises(ValueError):
        OutputView(kind="container", item="")
    with pytest.raises(ValueError):
        OutputView(kind="record", item="current")
    with pytest.raises(ValueError):
        OutputView(kind="rows", rows="rows", item="current")
    with pytest.raises(ValueError):
        OutputView(kind="container", item="current", rows="rows")


def test_a_node_type_requires_an_output_view() -> None:
    with pytest.raises(TypeError):
        NodeType(
            type_id="test.bare",
            family="test",
            label="Bare",
            summary="Has no output view.",
            description="Test type. Constructing it without an output view fails.",
            trigger=False,
            inputs=(),
            outputs=(PortSpec("main", "Output."),),
            config_schema={"type": "object"},
            execute=lambda node, hooks: None,
        )


def test_every_registered_type_declares_its_output_view() -> None:
    types = list_node_types()
    assert {item.type_id for item in types} == set(_OUTPUT_VIEWS)
    for node in types:
        assert node.output_view == _OUTPUT_VIEWS[node.type_id]


def test_container_item_is_a_property_of_the_each_schema() -> None:
    for node in list_node_types():
        if node.output_view.kind != "container":
            continue
        refined = node.refine(_default_config(node.config_schema), {}, None)
        each = refined["each"]
        assert node.output_view.item in each["properties"], node.type_id


def test_output_view_keys_appear_in_the_refined_main_schema() -> None:
    for node in list_node_types():
        if node.refine is None:
            continue
        properties = _main_properties(
            node.refine(_default_config(node.config_schema), {}, None)
        )
        if properties is None:
            continue
        view = node.output_view
        keys = [key for key in (view.rows, view.dataset) if key is not None]
        keys.extend(view.metrics)
        missing = [key for key in keys if key not in properties]
        assert missing == [], node.type_id


def test_get_channel_node_types_publishes_output_view() -> None:
    import os

    os.environ.setdefault("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    from fastapi.testclient import TestClient

    from backend.admin.role_store import get_role_store
    from backend.admin.roles import seed_roles
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store
    from backend.main import app

    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    get_user_store().create_user(
        account="admin",
        display_name="Admin",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )
    with TestClient(app) as client:
        logged = client.post(
            "/auth/login", json={"account": "admin", "password": "secret"}
        )
        assert logged.status_code == 200, logged.text
        catalog = client.get("/channel-node-types")
    assert catalog.status_code == 200, catalog.text
    items = catalog.json()["items"]
    assert {item["type"] for item in items} == set(_OUTPUT_VIEWS)
    for item in items:
        assert item["output_view"] == _published_view(_OUTPUT_VIEWS[item["type"]])


def _published_view(view: OutputView) -> dict[str, Any]:
    document: dict[str, Any] = {"kind": view.kind, "metrics": list(view.metrics)}
    if view.rows is not None:
        document["rows"] = view.rows
    if view.dataset is not None:
        document["dataset"] = view.dataset
    if view.item is not None:
        document["item"] = view.item
    return document


def _default_config(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}
    return {
        name: prop["default"]
        for name, prop in properties.items()
        if isinstance(prop, dict) and "default" in prop
    }


def _main_properties(refined: Any) -> dict[str, Any] | None:
    if not isinstance(refined, dict):
        return None
    main = refined.get("main")
    if not isinstance(main, dict):
        return None
    properties = main.get("properties")
    if not isinstance(properties, dict):
        return None
    return properties


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
