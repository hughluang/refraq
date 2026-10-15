"""Node executors for the linear runner."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping

from backend.channel.engine import EngineHooks, NodeResult
from backend.channel.nodes import list_node_types
from backend.channel.references import ChannelReferenceResolver
from backend.channel.reshape import (
    run_deduplicate,
    run_filter,
    run_for,
    run_if,
    run_merge,
    run_set_fields,
)
from backend.channel.sandbox import CodeError
from backend.channel.sql_read import ITEM_LIMIT, SqlReadError, run_channel_sql
from backend.channel.template import TemplateTypeError, output_matches, render
from backend.channel.values import LIST_OF_OBJECTS
from backend.channel.variables import VALUE_MAX_BYTES, get_variable_store, valid_name, value_size
from backend.core.errors import AppError
from backend.core.time import format_instant, utc_now
from backend.entity.errors import EntityRowWriteFailed
from backend.entity.rows import head_target, write_rows
from backend.metadata.query.service import run_controlled_query

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
    editor = _editor(hooks)
    try:
        output = run_channel_sql(
            str(statement),
            source=config["source"],
            statement_timeout_sec=config.get("statement_timeout_sec", 30),
            max_rows=editor.row_limit if editor is not None else ITEM_LIMIT,
            rollback=editor is not None,
            strict_limit=editor is None,
            editor=editor is not None,
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
    ttl_sec = config.get("ttl_sec") if writes else None
    if _editor(hooks) is not None and operation != "get":
        output = _dry_variable(
            operation=operation,
            name=name,
            value=value,
            expected=expected,
            ttl_sec=ttl_sec,
        )
        return _checked("state.variable", node, NodeResult(status="succeeded", output=output))
    result = get_variable_store().apply(
        operation=operation,
        name=name,
        value=value,
        expected=expected,
        ttl_sec=ttl_sec,
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
    projected, error = _project(source, config.get("mapping") or [])
    if error is not None:
        return error
    try:
        dry_run = _editor(hooks) is not None
        result = write_rows(
            str(config["entity_id"]),
            mode=mode,
            match_key=config.get("match_key"),
            rows=projected,
            user=hooks.user,  # type: ignore[attr-defined]
            statement_timeout_ms=STATEMENT_TIMEOUT_MS,
            dry_run=dry_run,
        )
    except EntityRowWriteFailed as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=(
                exc.message
                if exc.row_index is None
                else f"Source object {exc.row_index}: {exc.message}"
            ),
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
    output: dict[str, Any] = {
        "inserted": result.inserted,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "deleted": result.deleted,
        "unmatched": result.unmatched,
    }
    if _editor(hooks) is not None:
        output["dry_run"] = True
    return _checked(
        "write.entity",
        node,
        NodeResult(status="succeeded", output=output),
    )


def _editor(hooks: EngineHooks) -> Any | None:
    """Editor options on the hooks, or None for a real Channel Run."""
    return getattr(hooks, "editor", None)


def _dry_variable(
    *,
    operation: str,
    name: str,
    value: Any,
    expected: Any,
    ttl_sec: int | None,
) -> dict[str, Any]:
    """The write result computed from the current value, without storing it."""
    current = get_variable_store().apply(operation="get", name=name)
    applied = _dry_applied(operation, current.found, current.value, expected)
    if operation == "delete":
        return {
            "name": name,
            "found": False,
            "value": None,
            "applied": applied,
            "expires_at": None,
            "dry_run": True,
        }
    if applied:
        expires = None if ttl_sec is None else utc_now() + timedelta(seconds=int(ttl_sec))
        return {
            "name": name,
            "found": True,
            "value": value,
            "applied": True,
            "expires_at": format_instant(expires) if expires is not None else None,
            "dry_run": True,
        }
    expires_at = (
        format_instant(current.expires_at) if current.expires_at is not None else None
    )
    return {
        "name": name,
        "found": current.found,
        "value": current.value,
        "applied": False,
        "expires_at": expires_at,
        "dry_run": True,
    }


def _dry_applied(operation: str, found: bool, current: Any, expected: Any) -> bool:
    if operation == "set":
        return True
    if operation == "set_if_absent":
        return not found
    if operation == "compare_and_set":
        return found and current == expected
    if operation == "delete":
        return found
    return False


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
    if not isinstance(refined, dict):
        return result
    for port in spec.outputs:
        if port.loop_back or port.port == "error":
            continue
        schema = refined.get(port.port)
        if isinstance(schema, dict) and not output_matches(result.output, schema):
            return NodeResult(
                status="failed",
                error_code="CHANNEL_OUTPUT_SCHEMA_MISMATCH",
                error_message="Output does not match the declared schema",
            )
    return result


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
) -> tuple[list[dict[str, Any]], NodeResult | None]:
    consumed = {entry["key"] for entry in mapping}
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(source):
        projected: dict[str, Any] = {
            key: value for key, value in item.items() if key not in consumed
        }
        for entry in mapping:
            key = entry["key"]
            if key not in item:
                return [], NodeResult(
                    status="failed",
                    error_code="CHANNEL_NODE_FAILED",
                    error_message=(
                        f"Source object {index} has no key '{key}' "
                        f"for attribute '{entry['attribute']}'"
                    ),
                    error_detail={"row_index": index, "attribute": entry["attribute"]},
                )
            projected[entry["attribute"]] = item[key]
        rows.append(projected)
    return rows, None


def execute_code(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    source = config.get("code")
    if not isinstance(source, str):
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="Code is missing",
            error_detail={"reason": "error"},
        )
    timeout = config.get("timeout_sec", 30)
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        timeout = 30
    try:
        value = hooks.sandbox.run_code(source, float(timeout))  # type: ignore[attr-defined]
    except CodeError as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
            error_detail=exc.detail,
        )
    return _checked("transform.code", node, NodeResult(status="succeeded", output=value))


def execute_source_query(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    try:
        statement = _value(hooks, config.get("sql"), {"type": "string"})
    except TemplateTypeError as exc:
        return _type_failed(config.get("sql"), exc)
    except Exception as exc:  # noqa: BLE001
        return _expr_failed(config.get("sql"), exc)
    row_cap = config.get("row_cap", 100)
    if not isinstance(row_cap, int) or isinstance(row_cap, bool):
        row_cap = 100
    editor = _editor(hooks)
    if editor is not None:
        row_cap = min(row_cap, editor.row_limit)
    user = hooks.user  # type: ignore[attr-defined]
    audit_detail = {
        key: value
        for key, value in {
            "channel_id": getattr(hooks, "_channel_id", None),
            "job_id": getattr(hooks, "job_id", None),
            "node_id": node.get("id"),
        }.items()
        if value
    }
    try:
        outcome = run_controlled_query(
            source_id=str(config["source_id"]),
            sql=str(statement),
            max_rows=row_cap,
            actor_user_id=user.id,
            actor_token_id=None,
            audit_detail=audit_detail or None,
        )
    except AppError as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=exc.message,
            error_detail={"code": exc.code},
        )
    rows = [dict(zip(outcome.columns, row)) for row in outcome.rows]
    return _checked(
        "read.source_query",
        node,
        NodeResult(
            status="succeeded",
            output={"rows": rows, "count": len(rows), "truncated": outcome.truncated},
        ),
    )


def execute_set_fields(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    return _checked("transform.set_fields", node, run_set_fields(node, hooks))


def execute_if(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    return _checked("transform.if", node, run_if(node, hooks))


def execute_filter(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    return _checked("transform.filter", node, run_filter(node, hooks))


def execute_merge(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    return _checked("transform.merge", node, run_merge(node, hooks))


def execute_deduplicate(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    return _checked("transform.deduplicate", node, run_deduplicate(node, hooks))


def execute_for(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    return _checked("volume.for", node, run_for(node, hooks))


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
    return list(dict.fromkeys(reasons))


EXECUTORS = {
    "trigger.manual": execute_manual,
    "trigger.scheduled": execute_scheduled,
    "read.sql": execute_sql,
    "read.source_query": execute_source_query,
    "transform.code": execute_code,
    "transform.set_fields": execute_set_fields,
    "transform.if": execute_if,
    "transform.filter": execute_filter,
    "transform.merge": execute_merge,
    "transform.deduplicate": execute_deduplicate,
    "volume.for": execute_for,
    "state.variable": execute_variable,
    "write.entity": execute_write,
}
