"""Template Preview and Node Sample against one recorded Channel Run.

Both read through one binder. Ancestors come from the submitted graph.
Executions match by node id. A container the node sits in contributes that
round's step, not the container's stored output. No node executes, no Source
is read, and nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from backend.channel.errors import ChannelRequestInvalid, ChannelRunNotFound
from backend.channel.graph import (
    _crosses_frame,
    _template_fields,
    ancestor_closure,
    template_site,
)
from backend.channel.nodes import list_node_types
from backend.channel.references import ChannelReferenceResolver
from backend.channel.run_store import (
    PREVIEW_LIST_CAP,
    NodeExecutionRecord,
    get_run_store,
    output_preview_with_truncated,
)
from backend.channel.sandbox import ExpressionError, SandboxFailed, SandboxSession
from backend.channel.template import TemplateSyntaxError, TemplateTypeError, parse, render

__all__ = ["node_sample", "preview_template"]

_OK_STATUSES = ("succeeded", "skipped")


@dataclass
class _Slot:
    node_id: str
    source: str
    state: str
    seq: int | None
    stored: Any
    totals: dict[str, int]
    error: dict[str, Any] | None
    referenced: bool
    ref: str
    name: str
    type_id: str
    preview_only: bool


@dataclass
class _Sample:
    scope: list[dict[str, Any]]
    config_changed: bool
    upstream: list[_Slot]
    node: dict[str, Any]


def preview_template(
    *,
    channel_id: str,
    job_id: str,
    graph: Mapping[str, Any],
    node_id: str,
    path: Sequence[str | int],
    scope: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    run, sample = _load(channel_id, job_id, graph, node_id, scope)
    site = template_site(graph, node_id, path, ChannelReferenceResolver(channel_id))
    if site is None:
        raise ChannelRequestInvalid("node_id and path do not name a template field")
    bindings = _bindings(sample.upstream)
    refused = next((item for item in site.problems if item.severity == "error"), None)
    if refused is not None:
        return _failed(refused.code, refused.detail, sample.scope, bindings)
    if site.value_schema is None:
        return _failed(
            "CHANNEL_REFERENCE_UNRESOLVED",
            "Declared value type does not resolve",
            sample.scope,
            bindings,
        )
    template = parse(site.text)
    named = _named_ids(template, graph)
    slots = {slot.node_id: slot for slot in sample.upstream}
    order = [
        str(node["id"])
        for node in graph["nodes"]
        if isinstance(node, dict) and "id" in node
    ]
    missing = [
        key
        for key in order
        if key in named and (key not in slots or slots[key].state == "not_recorded")
    ]
    context_missing = bool(template.contexts) and run.context is None
    if missing or context_missing:
        return {
            "state": "missing",
            "node_ids": missing,
            "context": context_missing,
            "scope": sample.scope,
            "bindings": bindings,
        }
    nodes = {
        str(node["id"]): node
        for node in graph["nodes"]
        if isinstance(node, dict) and "id" in node
    }
    try:
        with SandboxSession() as sandbox:
            if run.context is not None:
                sandbox.set_context(**run.context)
            for slot in sample.upstream:
                if slot.node_id not in named or slot.state == "not_recorded":
                    continue
                node = nodes[slot.node_id]
                sandbox.put_output(
                    ref=str(node["ref"]),
                    name=str(node["name"]),
                    output=slot.stored,
                )
            try:
                value = render(site.text, sandbox.evaluate, site.value_schema)
            except TemplateTypeError as exc:
                return _failed("CHANNEL_VALUE_TYPE_MISMATCH", str(exc), sample.scope, bindings)
            except (ExpressionError, SandboxFailed) as exc:
                return _failed("CHANNEL_NODE_FAILED", str(exc), sample.scope, bindings)
    except SandboxFailed as exc:
        return _failed("CHANNEL_SANDBOX_FAILED", str(exc), sample.scope, bindings)
    shown, truncated = output_preview_with_truncated(value)
    return {
        "state": "ok",
        "value": shown,
        "truncated": truncated,
        "scope": sample.scope,
        "bindings": bindings,
    }


def node_sample(
    *,
    channel_id: str,
    job_id: str,
    graph: Mapping[str, Any],
    node_id: str,
    scope: Sequence[Mapping[str, Any]] | None = None,
    container_round: int | None = None,
) -> dict[str, Any]:
    _run, sample = _load(channel_id, job_id, graph, node_id, scope, container_round)
    return {
        "scope": sample.scope,
        "config_changed": sample.config_changed,
        "upstream": [_present_upstream(slot) for slot in sample.upstream],
        "node": sample.node,
    }


def _load(
    channel_id: str,
    job_id: str,
    graph: Mapping[str, Any],
    node_id: str,
    scope: Sequence[Mapping[str, Any]] | None,
    container_round: int | None = None,
) -> tuple[Any, _Sample]:
    store = get_run_store()
    run = store.get_run(job_id)
    if run is None or run.channel_id != channel_id:
        raise ChannelRunNotFound()
    return run, _bind(store, run, graph, node_id, scope, container_round)


def _bind(
    store: Any,
    run: Any,
    graph: Mapping[str, Any],
    node_id: str,
    scope: Sequence[Mapping[str, Any]] | None,
    container_round: int | None = None,
) -> _Sample:
    frames = _frames(graph, node_id)
    if frames is None:
        raise ChannelRequestInvalid("node_id is not a node of the graph")
    requested = _requested_scope(scope, frames)
    if requested is None:
        latest = _latest_execution(store, run.job_id, node_id=node_id)
        resolved = (
            _scope_from_execution(store, run.job_id, latest)
            if latest is not None
            else _scope_from_frames(store, run.job_id, frames)
        )
    else:
        resolved = _scope_for_request(store, run.job_id, requested)
    by_id = _nodes(graph)
    node = by_id[node_id]
    referenced = _referenced_ids(graph, node, run.channel_id)
    ancestors = ancestor_closure(graph, node_id) or set()
    ancestors.discard(node_id)
    ordered = _ordered_ancestors(graph, ancestors)
    ranked = [item for item in ordered if item in referenced]
    ranked.extend(item for item in ordered if item not in referenced)
    levels = {level["container_node_id"]: level for level in resolved}
    upstream = [
        _ancestor_slot(
            store,
            run.job_id,
            by_id[item],
            levels,
            referenced=item in referenced,
        )
        for item in ranked
        if item in by_id
    ]
    selected = _select_node(store, run.job_id, node_id, resolved)
    presented = _present_node(selected)
    if (
        str(node.get("type")) == "volume.until"
        and container_round is not None
        and selected is not None
    ):
        presented = _overlay_until_condition(
            store, run.job_id, selected.seq, container_round, presented
        )
    return _Sample(
        scope=resolved,
        config_changed=_config_changed(run.graph, node_id, node.get("config")),
        upstream=upstream,
        node=presented,
    )


def _frames(graph: Mapping[str, Any], node_id: str) -> list[str] | None:
    by_id = _nodes(graph)
    if node_id not in by_id:
        return None
    containers = {
        item.type_id for item in list_node_types() if item.container is not None
    }
    chain: list[str] = []
    seen = {node_id}
    current = node_id
    while True:
        parent = by_id[current].get("parent")
        if not isinstance(parent, str) or not parent or parent in seen or parent not in by_id:
            break
        seen.add(parent)
        if str(by_id[parent].get("type")) in containers:
            chain.append(parent)
        current = parent
    chain.reverse()
    return chain


def _requested_scope(
    raw: Sequence[Mapping[str, Any]] | None,
    frames: list[str],
) -> list[tuple[str, int]] | None:
    if raw is None:
        return None
    if len(raw) != len(frames):
        raise ChannelRequestInvalid("scope does not match the node's container frames")
    parsed: list[tuple[str, int]] = []
    for item, expected in zip(raw, frames, strict=True):
        if not isinstance(item, Mapping) or item.get("container_node_id") != expected:
            raise ChannelRequestInvalid("scope does not match the node's container frames")
        round_index = item.get("round")
        if isinstance(round_index, bool) or not isinstance(round_index, int) or round_index < 0:
            raise ChannelRequestInvalid("round must be an integer greater than or equal to 0")
        parsed.append((expected, round_index))
    return parsed


def _scope_from_execution(store: Any, job_id: str, execution: NodeExecutionRecord) -> list[dict[str, Any]]:
    chain: list[tuple[str, int, int]] = []
    seen: set[int] = set()
    container_seq = execution.container_seq
    round_index = execution.round
    while container_seq is not None and container_seq not in seen:
        seen.add(container_seq)
        container = store.get_execution(job_id, container_seq)
        if container is None:
            break
        chain.append(
            (str(container.node_id), container_seq, 0 if round_index is None else int(round_index))
        )
        round_index = container.round
        container_seq = container.container_seq
    chain.reverse()
    return [
        _level(store, job_id, container_node_id, seq, index)
        for container_node_id, seq, index in chain
    ]


def _scope_from_frames(store: Any, job_id: str, frames: list[str]) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    outer_seq: int | None = None
    outer_round: int | None = None
    for index, container_node_id in enumerate(frames):
        if index > 0 and outer_seq is None:
            levels.append(_level(store, job_id, container_node_id, None, 0))
            continue
        chosen = _latest_execution(
            store,
            job_id,
            node_id=container_node_id,
            container_seq=None if index == 0 else outer_seq,
            round_index=None if index == 0 else outer_round,
        )
        last = None if chosen is None else _last_round_index(store, job_id, chosen.seq)
        if chosen is None or last is None:
            levels.append(_level(store, job_id, container_node_id, None, 0))
            outer_seq = None
            continue
        levels.append(_level(store, job_id, container_node_id, chosen.seq, last))
        outer_seq = chosen.seq
        outer_round = last
    return levels


def _scope_for_request(
    store: Any,
    job_id: str,
    requested: list[tuple[str, int]],
) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    outer_seq: int | None = None
    outer_round: int | None = None
    for index, (container_node_id, round_index) in enumerate(requested):
        if index > 0 and outer_seq is None:
            levels.append(_level(store, job_id, container_node_id, None, round_index))
            continue
        chosen = _latest_execution(
            store,
            job_id,
            node_id=container_node_id,
            container_seq=None if index == 0 else outer_seq,
            round_index=None if index == 0 else outer_round,
        )
        seq = chosen.seq if chosen is not None and _rounds_total(store, job_id, chosen.seq) else None
        levels.append(_level(store, job_id, container_node_id, seq, round_index))
        if seq is None:
            outer_seq = None
        else:
            outer_seq = seq
            outer_round = round_index
    return levels


def _level(
    store: Any,
    job_id: str,
    container_node_id: str,
    container_seq: int | None,
    round_index: int,
) -> dict[str, Any]:
    total = _rounds_total(store, job_id, container_seq) if container_seq is not None else 0
    if container_seq is None or total == 0:
        return {
            "container_node_id": container_node_id,
            "container_seq": None,
            "round": round_index,
            "rounds_total": 0,
        }
    return {
        "container_node_id": container_node_id,
        "container_seq": container_seq,
        "round": round_index,
        "rounds_total": total,
    }


def _rounds_total(store: Any, job_id: str, container_seq: int) -> int:
    _items, total = store.query_rounds(job_id, container_seq, limit=1, offset=0)
    return int(total)


def _last_round_index(store: Any, job_id: str, container_seq: int) -> int | None:
    total = _rounds_total(store, job_id, container_seq)
    if total <= 0:
        return None
    items, _total = store.query_rounds(job_id, container_seq, limit=1, offset=total - 1)
    if not items:
        return None
    return int(items[-1].round)


def _latest_execution(
    store: Any,
    job_id: str,
    *,
    node_id: str,
    container_seq: int | None = None,
    round_index: int | None = None,
    status: str | None = None,
) -> NodeExecutionRecord | None:
    _page, total = store.query_executions(
        job_id,
        node_id=node_id,
        container_seq=container_seq,
        round_index=round_index,
        status=status,
        limit=1,
        offset=0,
    )
    if total <= 0:
        return None
    page, _total = store.query_executions(
        job_id,
        node_id=node_id,
        container_seq=container_seq,
        round_index=round_index,
        status=status,
        limit=1,
        offset=total - 1,
    )
    return page[-1] if page else None


def _preferred(
    store: Any,
    job_id: str,
    *,
    node_id: str,
    container_seq: int | None,
    round_index: int | None,
    constrained: bool,
) -> tuple[NodeExecutionRecord | None, str]:
    filters: dict[str, Any] = {}
    if constrained:
        filters["container_seq"] = container_seq
        filters["round_index"] = round_index
    best: NodeExecutionRecord | None = None
    for status in _OK_STATUSES:
        found = _latest_execution(store, job_id, node_id=node_id, status=status, **filters)
        if found is not None and (best is None or found.seq > best.seq):
            best = found
    if best is not None:
        return best, "ok"
    failed = _latest_execution(store, job_id, node_id=node_id, status="failed", **filters)
    if failed is not None:
        return failed, "failed"
    return None, "not_recorded"


def _select_node(
    store: Any,
    job_id: str,
    node_id: str,
    scope: list[dict[str, Any]],
) -> NodeExecutionRecord | None:
    if not scope:
        return _latest_execution(store, job_id, node_id=node_id)
    inner = scope[-1]
    if inner["container_seq"] is None:
        return None
    return _latest_execution(
        store,
        job_id,
        node_id=node_id,
        container_seq=inner["container_seq"],
        round_index=inner["round"],
    )


def _ancestor_slot(
    store: Any,
    job_id: str,
    node: Mapping[str, Any],
    levels: Mapping[str, Mapping[str, Any]],
    *,
    referenced: bool,
) -> _Slot:
    node_id = str(node["id"])
    if node_id in levels:
        return _round_slot(store, job_id, node, levels[node_id], referenced=referenced)
    parent = node.get("parent")
    if isinstance(parent, str) and parent in levels:
        level = levels[parent]
        return _execution_slot(
            store,
            job_id,
            node,
            referenced=referenced,
            container_seq=level["container_seq"],
            round_index=level["round"],
            constrained=True,
        )
    return _execution_slot(
        store,
        job_id,
        node,
        referenced=referenced,
        container_seq=None,
        round_index=None,
        constrained=False,
    )


def _round_slot(
    store: Any,
    job_id: str,
    node: Mapping[str, Any],
    level: Mapping[str, Any],
    *,
    referenced: bool,
) -> _Slot:
    seq = level["container_seq"]
    found = None if seq is None else store.get_round(job_id, seq, level["round"])
    if found is None:
        return _filled_slot(
            node,
            source="round_step",
            state="not_recorded",
            seq=None,
            stored=None,
            totals={},
            error=None,
            referenced=referenced,
            preview_only=False,
        )
    return _filled_slot(
        node,
        source="round_step",
        state="ok",
        seq=None,
        stored=found.step,
        totals=dict(found.step_totals or {}),
        error=None,
        referenced=referenced,
        preview_only=False,
    )


def _execution_slot(
    store: Any,
    job_id: str,
    node: Mapping[str, Any],
    *,
    referenced: bool,
    container_seq: int | None,
    round_index: int | None,
    constrained: bool,
) -> _Slot:
    if constrained and container_seq is None:
        return _filled_slot(
            node,
            source="execution",
            state="not_recorded",
            seq=None,
            stored=None,
            totals={},
            error=None,
            referenced=referenced,
            preview_only=False,
        )
    record, state = _preferred(
        store,
        job_id,
        node_id=str(node["id"]),
        container_seq=container_seq,
        round_index=round_index,
        constrained=constrained,
    )
    if record is None:
        return _filled_slot(
            node,
            source="execution",
            state="not_recorded",
            seq=None,
            stored=None,
            totals={},
            error=None,
            referenced=referenced,
            preview_only=False,
        )
    return _filled_slot(
        node,
        source="execution",
        state=state,
        seq=record.seq,
        stored=record.output,
        totals=dict(record.preview_totals or {}),
        error=_error(record),
        referenced=referenced,
        preview_only=bool(record.preview_only),
    )


def _filled_slot(
    node: Mapping[str, Any],
    *,
    source: str,
    state: str,
    seq: int | None,
    stored: Any,
    totals: dict[str, int],
    error: dict[str, Any] | None,
    referenced: bool,
    preview_only: bool,
) -> _Slot:
    return _Slot(
        node_id=str(node["id"]),
        source=source,
        state=state,
        seq=seq,
        stored=stored,
        totals=totals,
        error=error,
        referenced=referenced,
        ref=str(node.get("ref")),
        name=str(node.get("name")),
        type_id=str(node.get("type")),
        preview_only=preview_only,
    )


def _present_upstream(slot: _Slot) -> dict[str, Any]:
    value, truncated, totals = _clip(slot.stored, slot.totals)
    return {
        "node_id": slot.node_id,
        "ref": slot.ref,
        "name": slot.name,
        "type_id": slot.type_id,
        "referenced": slot.referenced,
        "state": slot.state,
        "source": slot.source,
        "seq": slot.seq,
        "value": value,
        "truncated": truncated,
        "totals": totals,
        "error": slot.error,
        "preview_only": slot.preview_only,
    }


def _overlay_until_condition(
    store: Any,
    job_id: str,
    seq: int,
    round_index: int,
    presented: dict[str, Any],
) -> dict[str, Any]:
    """Show one round's condition on the sample the config panel already reads.

    The execution's stored input stays empty. This copy exists only on the response.
    """
    found = store.get_round(job_id, seq, round_index)
    if found is None or "until" not in found.step:
        return presented
    return {**presented, "input": {"until": found.step["until"]}}


def _present_node(record: NodeExecutionRecord | None) -> dict[str, Any]:
    if record is None:
        return {
            "state": "not_recorded",
            "seq": None,
            "status": None,
            "output": None,
            "output_truncated": False,
            "totals": {},
            "input": None,
            "input_totals": None,
            "error": None,
            "preview_only": False,
        }
    output, truncated, totals = _clip(record.output, record.preview_totals)
    if record.input is None:
        shown_input: Any = None
        input_totals = None
    else:
        shown_input, _input_truncated = output_preview_with_truncated(
            record.input, totals=record.input_totals
        )
        input_totals = record.input_totals
    return {
        "state": "ok" if record.status == "succeeded" else record.status,
        "seq": record.seq,
        "status": record.status,
        "output": output,
        "output_truncated": truncated,
        "totals": totals,
        "input": shown_input,
        "input_totals": input_totals,
        "error": _error(record),
        "preview_only": bool(record.preview_only),
    }


def _clip(value: Any, stored: Mapping[str, int] | None) -> tuple[Any, bool, dict[str, int]]:
    """Fold stored length maps with lists this response shortens.

    Stored ``preview_totals`` and ``step_totals`` already name every list the
    clipper walked, including lists that were not shortened. Those keys stay.
    A non-preview output stores an empty map, so an unshortened list adds nothing.
    """
    totals = {str(key): int(length) for key, length in (stored or {}).items()}
    for path, length in _shortened(value).items():
        current = totals.get(path)
        if current is None or length > current:
            totals[path] = length
    preview, truncated = output_preview_with_truncated(value, totals=stored)
    return preview, truncated, totals


def _shortened(value: Any, path: str = "") -> dict[str, int]:
    found: dict[str, int] = {}
    if isinstance(value, list):
        if len(value) > PREVIEW_LIST_CAP:
            found[path] = len(value)
        for index, item in enumerate(value[:PREVIEW_LIST_CAP]):
            child = str(index) if path == "" else f"{path}.{index}"
            found.update(_shortened(item, child))
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            child = str(key) if path == "" else f"{path}.{key}"
            found.update(_shortened(item, child))
    return found


def _error(record: NodeExecutionRecord) -> dict[str, Any] | None:
    if record.error_code is None and record.error_message is None:
        return None
    return {"code": record.error_code, "message": record.error_message}


def _config_changed(snapshot: Any, node_id: str, submitted: Any) -> bool:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("nodes"), list):
        return True
    for node in snapshot["nodes"]:
        if isinstance(node, dict) and str(node.get("id")) == node_id:
            return node.get("config") != submitted
    return True


def _referenced_ids(graph: Mapping[str, Any], node: Mapping[str, Any], channel_id: str) -> set[str]:
    spec = next(
        (item for item in list_node_types() if item.type_id == str(node.get("type"))),
        None,
    )
    config = node.get("config")
    if spec is None or not isinstance(config, dict):
        return set()
    found: set[str] = set()
    resolver = ChannelReferenceResolver(channel_id)
    for text, _schema, _path in _template_fields(spec.config_schema, config, None, resolver):
        try:
            template = parse(text)
        except TemplateSyntaxError:
            continue
        found.update(_named_ids(template, graph))
    return found


def _named_ids(template: Any, graph: Mapping[str, Any]) -> set[str]:
    by_ref: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict) or "id" not in node:
            continue
        by_ref.setdefault(str(node.get("ref")), []).append(str(node["id"]))
        by_name.setdefault(str(node.get("name")), []).append(str(node["id"]))
    found: set[str] = set()
    for ref in template.refs:
        found.update(by_ref.get(ref, ()))
    for name in template.node_names:
        found.update(by_name.get(name, ()))
    return found


def _nodes(graph: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(node["id"]): node
        for node in graph.get("nodes") or []
        if isinstance(node, dict) and "id" in node
    }


def _ordered_ancestors(graph: Mapping[str, Any], ancestors: set[str]) -> list[str]:
    by_id = _nodes(graph)
    incoming = {item: 0 for item in ancestors}
    outgoing: dict[str, list[str]] = {item: [] for item in ancestors}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source")
        target = edge.get("target")
        if not isinstance(source, dict) or not isinstance(target, dict):
            continue
        source_id = str(source.get("node_id"))
        target_id = str(target.get("node_id"))
        if source_id not in ancestors or target_id not in ancestors:
            continue
        if source_id not in by_id or target_id not in by_id:
            continue
        if _crosses_frame(source_id, target_id, by_id):
            continue
        outgoing[source_id].append(target_id)
        incoming[target_id] += 1
    ready = [item for item, count in incoming.items() if count == 0]
    ordered: list[str] = []
    seen: set[str] = set()
    while ready:
        ready.sort(key=lambda item: _position(by_id[item]))
        current = ready.pop(0)
        if current in seen:
            continue
        seen.add(current)
        ordered.append(current)
        for child in outgoing[current]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    rest = [item for item in ancestors if item not in seen and item in by_id]
    rest.sort(key=lambda item: _position(by_id[item]))
    ordered.extend(rest)
    return ordered


def _position(node: Mapping[str, Any]) -> tuple[float, float, str]:
    raw = node.get("position")
    position = raw if isinstance(raw, dict) else {}

    def _num(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0.0
        return float(value)

    return (_num(position.get("y")), _num(position.get("x")), str(node.get("id")))


def _bindings(upstream: list[_Slot]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for slot in upstream:
        item: dict[str, Any] = {"node_id": slot.node_id, "source": slot.source}
        if slot.source == "execution" and slot.seq is not None:
            item["seq"] = slot.seq
        found.append(item)
    return found


def _failed(
    code: str,
    message: str,
    scope: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "state": "failed",
        "code": code,
        "message": message,
        "scope": scope,
        "bindings": bindings,
    }
