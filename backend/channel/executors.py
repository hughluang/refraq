"""Node executors for the linear runner."""

from __future__ import annotations

from typing import Any, Mapping

from backend.channel.engine import EngineHooks, NodeResult
from backend.channel.expr import expression_body
from backend.entity.errors import EntityRowWriteFailed
from backend.entity.rows import head_target, read_rows, write_rows

ITEM_LIMIT = 10_000
STATEMENT_TIMEOUT_MS = 30_000

__all__ = ["EXECUTORS", "ITEM_LIMIT"]


def execute_manual(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    ctx = hooks  # type: ignore[attr-defined]
    payload = dict((node.get("config") or {}).get("payload") or {})
    actor = ctx.actor
    payload["triggered_by"] = {"id": actor["id"], "name": actor["name"]}
    payload["triggered_at"] = ctx.started_at
    return NodeResult(status="succeeded", output=payload)


def execute_read(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node["config"]
    filters = []
    for item in config.get("filters") or []:
        try:
            value = _value(hooks, item.get("value"))
        except Exception as exc:  # noqa: BLE001
            return _expr_failed(item.get("value"), exc)
        filters.append({"attribute": item["attribute"], "op": item.get("op", "eq"), "value": value})
    try:
        rows, _total = read_rows(
            config["entity_id"],
            filters=filters,
            user=hooks.user,  # type: ignore[attr-defined]
            limit=ITEM_LIMIT,
        )
    except EntityRowWriteFailed as exc:
        return NodeResult(
            status="failed",
            error_code="CHANNEL_ITEM_LIMIT_EXCEEDED",
            error_message=exc.message,
        )
    except Exception as exc:  # noqa: BLE001
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message=str(exc),
        )
    return NodeResult(status="succeeded", output={"rows": rows, "count": len(rows)})


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
        source = _value(hooks, config.get("source"))
    except Exception as exc:  # noqa: BLE001
        return _expr_failed(config.get("source"), exc)
    if not isinstance(source, list) or any(not isinstance(item, dict) for item in source):
        return NodeResult(
            status="failed",
            error_code="CHANNEL_NODE_FAILED",
            error_message="source is not a list of objects",
        )
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
    return NodeResult(
        status="succeeded",
        output={
            "inserted": result.inserted,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "deleted": result.deleted,
            "unmatched": result.unmatched,
        },
    )


def _value(hooks: EngineHooks, raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    body = expression_body(raw)
    if body is None:
        return raw
    return hooks.evaluate(body)  # type: ignore[attr-defined]


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
    "read.entity": execute_read,
    "write.entity": execute_write,
}
