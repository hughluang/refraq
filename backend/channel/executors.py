"""Node executors for the linear runner."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.engine import EngineHooks, NodeResult
from backend.channel.nodes import list_node_types
from backend.channel.references import ChannelReferenceResolver
from backend.channel.sql_read import SqlReadError, run_channel_sql
from backend.channel.template import TemplateTypeError, output_matches, render
from backend.channel.values import LIST_OF_OBJECTS
from backend.channel.variables import VALUE_MAX_BYTES, get_variable_store, valid_name, value_size
from backend.core.time import format_instant
from backend.entity.errors import EntityRowWriteFailed
from backend.entity.rows import head_target, write_rows

STATEMENT_TIMEOUT_MS = 30_000
_JSON = {"type": ["object", "array", "string", "number", "boolean", "null"]}

__all__ = ["EXECUTORS"]


def execute_manual(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    ctx = hooks  # type: ignore[attr-defined]
    payload = dict((node.get("config") or {}).get("payload") or {})
    actor = ctx.actor
    payload["triggered_by"] = {"id": actor["id"], "name": actor["name"]}
    payload["triggered_at"] = ctx.started_at
    return _checked(
        "trigger.manual", node, NodeResult(status="succeeded", output=payload)
    )


def execute_scheduled(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    schedule = getattr(hooks, "schedule")
    return _checked(
        "trigger.scheduled",
        node,
        NodeResult(
            status="succeeded",
            output={
                "schedule_id": schedule.get("schedule_id"),
                "name": schedule.get("name"),
                "scheduled_for": schedule.get("scheduled_for"),
            },
        ),
    )


def execute_sql(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    try:
        statement = _value(hooks, config.get("sql"), {"type": "string"})
    except TemplateTypeError as exc:
        return _type_failed(config.get("sql"), exc)
    except Exception as exc:  # noqa: BLE001
        return _expr_failed(config.get("sql"), exc)
    try:
        output = run_channel_sql(
            str(statement),
            source=config["source"],
            statement_timeout_sec=config.get("statement_timeout_sec", 30),
        )
    except SqlReadError as exc:
        return NodeResult(status="failed", error_code=exc.code, error_message=exc.message)
    return _checked("read.sql", node, NodeResult(status="succeeded", output=output))


def execute_variable(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    operation = str(config.get("operation") or "")
    try:
        name = str(_value(hooks, config.get("name"), {"type": "string"}))
    except TemplateTypeError as exc:
        return _type_failed(config.get("name"), exc)
    except Exception as exc:  # noqa: BLE001
        return _expr_failed(config.get("name"), exc)
    if not valid_name(name):
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Variable name is invalid",
        )
    value = None
    expected = None
    writes = operation in {"set", "set_if_absent", "compare_and_set"}
    if writes:
        try:
            value = _value(hooks, config.get("value"), _JSON)
        except TemplateTypeError as exc:
            return _type_failed(config.get("value"), exc)
        except Exception as exc:  # noqa: BLE001
            return _expr_failed(config.get("value"), exc)
        if value_size(value) > VALUE_MAX_BYTES:
            return NodeResult(
                status="failed",
                error_code="CHANNEL_VARIABLE_TOO_LARGE",
                error_message="Variable value exceeds 64 KiB",
            )
    if operation == "compare_and_set":
        try:
            expected = _value(hooks, config.get("expected"), _JSON)
        except TemplateTypeError as exc:
            return _type_failed(config.get("expected"), exc)
        except Exception as exc:  # noqa: BLE001
            return _expr_failed(config.get("expected"), exc)
    result = get_variable_store().apply(
        operation=operation,
        name=name,
        value=value,
        expected=expected,
        ttl_sec=config.get("ttl_sec") if writes else None,
    )
    expires = format_instant(result.expires_at) if result.expires_at is not None else None
    return _checked(
        "state.variable",
        node,
        NodeResult(
            status="succeeded",
            output={
                "name": result.name,
                "found": result.found,
                "value": result.value,
                "applied": result.applied,
                "expires_at": expires,
            },
        ),
    )


def execute_write(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    target = head_target(str(config["entity_id"]))
    if target is None:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Target entity has no head",
        )
    reasons = _incompatible(config, target)
    if reasons:
        if config.get("on_incompatible_head") == "skip":
            return NodeResult(
                status="skipped",
                output={"skipped": True, "reasons": reasons},
                error_message="incompatible head",
            )
        return NodeResult(
            status="failed",
            error_code="CHANNEL_WRITE_INCOMPATIBLE",
            error_message="Write mapping is incompatible with the current head",
            error_detail={"reasons": reasons},
        )
    try:
        source = _value(hooks, config.get("source"), LIST_OF_OBJECTS)
    except TemplateTypeError as exc:
        return _type_failed(config.get("source"), exc)
    except Exception as exc:  # noqa: BLE001
        return _expr_failed(config.get("source"), exc)
    mode = config["mode"]
    projected, error = _project(source, config.get("mapping") or [], mode)
    if error is not None:
        return error
    try:
        result = write_rows(
            str(config["entity_id"]),
            mode=mode,
            match_key=config.get("match_key"),
            rows=projected,
            user=hooks.user,  # type: ignore[attr-defined]
            statement_timeout_ms=STATEMENT_TIMEOUT_MS,
        )
    except EntityRowWriteFailed as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=exc.message,
            error_detail={
                "row_index": exc.row_index,
                "attribute": exc.attribute,
                "value": exc.value,
                "reason": exc.reason,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
        )
    return _checked(
        "write.entity",
        node,
        NodeResult(
            status="succeeded",
            output={
                "inserted": result.inserted,
                "updated": result.updated,
                "unchanged": result.unchanged,
                "deleted": result.deleted,
                "unmatched": result.unmatched,
            },
        ),
    )


def _value(hooks: EngineHooks, raw: Any, schema: Mapping[str, Any]) -> Any:
    if not isinstance(raw, str):
        raise TemplateTypeError("Template value must be text")
    return render(raw, hooks.evaluate, schema)  # type: ignore[attr-defined]


def _checked(type_id: str, node: Mapping[str, Any], result: NodeResult) -> NodeResult:
    if result.status != "succeeded":
        return result
    spec = next((item for item in list_node_types() if item.type_id == type_id), None)
    if spec is None or spec.refine is None:
        return result
    config = node.get("config") if isinstance(node.get("config"), dict) else {}
    refined = spec.refine(config, {}, ChannelReferenceResolver("_"))
    schema = refined.get("main") if isinstance(refined, dict) else None
    if not isinstance(schema, dict) or output_matches(result.output, schema):
        return result
    return NodeResult(
        status="failed",
        error_code="CHANNEL_OUTPUT_SCHEMA_MISMATCH",
        error_message="Output does not match the declared schema",
    )


def _type_failed(raw: Any, exc: Exception) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_VALUE_TYPE_MISMATCH",
        error_message=str(exc),
        error_detail={"expression": raw},
    )


def _expr_failed(raw: Any, exc: Exception) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_NODE_FAILED",
        error_message=str(exc),
        error_detail={"expression": raw},
    )


def _project(
    source: list[dict[str, Any]],
    mapping: list[dict[str, Any]],
    mode: str,
) -> tuple[list[dict[str, Any]], NodeResult | None]:
    if mode == "delete":
        return source, None
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(source):
        projected: dict[str, Any] = {}
        for entry in mapping:
            key = entry["key"]
            if key not in item:
                return [], NodeResult(
                    status="failed",
                    error_code="CHANNEL_NODE_FAILED",
                    error_message=f"Source object is missing key {key}",
                    error_detail={"row_index": index, "attribute": entry["attribute"]},
                )
            projected[entry["attribute"]] = item[key]
        rows.append(projected)
    return rows, None


def _incompatible(config: Mapping[str, Any], target: Any) -> list[str]:
    attrs = {attr.name: attr for attr in target.attributes}
    reasons: list[str] = []
    mapped = {
        item["attribute"]
        for item in config.get("mapping") or []
        if isinstance(item, dict) and "attribute" in item
    }
    match = config.get("match_key")
    if match is None:
        marked = next((attr for attr in target.attributes if attr.business_key), None)
        if marked is None:
            reasons.append("business_key_missing")
        else:
            match = marked.name
    if isinstance(match, str):
        attr = attrs.get(match)
        if attr is None:
            reasons.append("attribute_missing")
        elif not attr.unique:
            reasons.append("match_key_not_unique")
    for name in mapped:
        if name not in attrs:
            reasons.append("attribute_missing")
    if config.get("mode") in {"upsert", "create"}:
        for attr in target.attributes:
            if attr.required and attr.name not in mapped:
                reasons.append("required_unmapped")
    return list(dict.fromkeys(reasons))


EXECUTORS = {
    "trigger.manual": execute_manual,
    "trigger.scheduled": execute_scheduled,
    "read.sql": execute_sql,
    "state.variable": execute_variable,
    "write.entity": execute_write,
}
