"""Template Preview: one Template Field evaluated against a recorded Channel Run.

The run's recorded Expression Context and the recorded outputs of the upstream
nodes the template names go into a fresh sandbox, and `render` converts the
result as a run does. No node executes and nothing is written.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from backend.channel.errors import ChannelRequestInvalid, ChannelRunNotFound
from backend.channel.graph import template_site
from backend.channel.references import ChannelReferenceResolver
from backend.channel.run_store import get_run_store, output_preview
from backend.channel.sandbox import ExpressionError, SandboxFailed, SandboxSession
from backend.channel.template import TemplateTypeError, parse, render

__all__ = ["preview_template"]

# Execution statuses whose recorded output later expressions read.
_IN_SCOPE = frozenset({"succeeded", "skipped"})


def preview_template(
    *,
    channel_id: str,
    job_id: str,
    graph: Mapping[str, Any],
    node_id: str,
    path: Sequence[str | int],
) -> dict[str, Any]:
    store = get_run_store()
    run = store.get_run(job_id)
    if run is None or run.channel_id != channel_id:
        raise ChannelRunNotFound()
    site = template_site(graph, node_id, path, ChannelReferenceResolver(channel_id))
    if site is None:
        raise ChannelRequestInvalid("node_id and path do not name a template field")
    refused = next((item for item in site.problems if item.severity == "error"), None)
    if refused is not None:
        return _failed(refused.code, refused.detail)
    if site.value_schema is None:
        return _failed("CHANNEL_REFERENCE_UNRESOLVED", "Declared value type does not resolve")

    template = parse(site.text)
    nodes = {str(node["id"]): node for node in graph["nodes"]}
    by_ref = {str(node["ref"]): key for key, node in nodes.items()}
    by_name = {str(node["name"]): key for key, node in nodes.items()}
    named = {by_ref[ref] for ref in template.refs} | {
        by_name[name] for name in template.node_names
    }
    outputs: dict[str, Any] = {}
    for item in store.list_executions(job_id):
        if item.node_id in named and item.status in _IN_SCOPE:
            outputs[item.node_id] = item.output
    missing = [key for key in nodes if key in named and key not in outputs]
    context_missing = bool(template.contexts) and run.context is None
    if missing or context_missing:
        return {"state": "missing", "node_ids": missing, "context": context_missing}

    try:
        with SandboxSession() as sandbox:
            if run.context is not None:
                sandbox.set_context(**run.context)
            for key, output in outputs.items():
                node = nodes[key]
                sandbox.put_output(ref=str(node["ref"]), name=str(node["name"]), output=output)
            try:
                value = render(site.text, sandbox.evaluate, site.value_schema)
            except TemplateTypeError as exc:
                return _failed("CHANNEL_VALUE_TYPE_MISMATCH", str(exc))
            except (ExpressionError, SandboxFailed) as exc:
                return _failed("CHANNEL_NODE_FAILED", str(exc))
    except SandboxFailed as exc:
        return _failed("CHANNEL_SANDBOX_FAILED", str(exc))
    shown = output_preview(value)
    return {"state": "ok", "value": shown, "truncated": shown != value}


def _failed(code: str, message: str) -> dict[str, Any]:
    return {"state": "failed", "code": code, "message": message}
