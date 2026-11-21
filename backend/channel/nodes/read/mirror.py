"""Pinned mirror snapshot node with authorized run-scoped paging."""

from backend.channel.mirror_reads import resolve_object
from backend.channel.nodes.spec import (
    MAIN_INPUT, MAIN_OUTPUT, NodeResult, NodeType, OutputView, Problem, object_schema,
)
from backend.core.errors import AppError

__all__ = ["NODE_TYPE"]


def _check(config, resolver):
    del resolver
    try:
        resolve_object(config["object_id"])
    except AppError:
        return [Problem("MIRROR_READ_UNAVAILABLE", "Mirror binding or gateway is unavailable")]
    return []


def _execute(node, hooks):
    config = node["config"]
    rows = []
    after = None
    try:
        while True:
            page = hooks.read_mirror_page(object_id=config["object_id"], after_key=after, limit=500)
            freshness = page["freshness"]
            status = freshness.get("status") if isinstance(freshness, dict) else freshness
            if status != "ready":
                policy = config["freshness_policy"]
                if policy == "fail" or (policy == "skip" and status != "stale"):
                    return NodeResult(status="failed", error_code="MIRROR_READ_UNAVAILABLE",
                                      error_message="Mirror freshness requirement is not met")
                if policy == "skip":
                    return NodeResult(status="succeeded", output=dict(
                        rows=[], generation_id=page["generation_id"],
                        freshness=freshness, source_ids=page["source_ids"]))
            rows.extend(page["rows"])
            next_key = page["next_key"]
            if next_key is None:
                break
            if next_key == after:
                return NodeResult(status="failed", error_code="MIRROR_READ_UNAVAILABLE",
                                  error_message="Mirror keyset did not advance")
            after = next_key
    except AppError as exc:
        return NodeResult(status="failed", error_code=exc.code,
                          error_message="Mirror read failed")
    return NodeResult(status="succeeded", output=dict(
        rows=rows, generation_id=page["generation_id"],
        freshness=freshness, source_ids=page["source_ids"]))


NODE_TYPE = NodeType(
    type_id="read.mirror", family="read", label="Mirror", trigger=False,
    summary="Reads a complete generation pinned to this run.",
    description="Reads authorized mirror rows with stable keyset paging and Source provenance. The run retains one generation across pages and restarts.",
    inputs=(MAIN_INPUT,), outputs=(MAIN_OUTPUT,),
    config_schema=object_schema({
        "object_id": {"type": "string", "minLength": 1, "title": "Catalog Object",
                      "description": "Catalog Object whose Source mirror supplies rows."},
        "freshness_policy": {"type": "string", "enum": ["continue", "skip", "fail"],
                             "title": "Freshness policy",
                             "description": "Continue with annotations, skip stale rows, or fail when not ready."},
    }, ["object_id", "freshness_policy"]),
    output_view=OutputView(kind="rows", rows="rows"),
    execute=_execute, check=_check,
)
