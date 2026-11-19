"""Bounded live Mirror history consumed by incremental Channel nodes."""

import json
from dataclasses import dataclass

from backend.channel.checkpoints import MirrorCheckpointInvalid, MirrorCheckpointPosition

SOURCE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "title": "Mirror source", "description": "Reads the bounded live history of an existing mirror. Never opens capture.",
    "properties": {"kind": {"const": "mirror", "title": "Kind", "description": "Mirror history stream."},
                   "mirror_id": {"type": "string", "minLength": 1, "maxLength": 64,
                                 "title": "Mirror", "description": "Immutable mirror stream identity."}},
    "required": ["kind", "mirror_id"],
}


def source_schema(schema):
    schema["properties"]["source"] = SOURCE_SCHEMA
    schema["required"] = []
    schema["oneOf"] = [
        {"required": ["entity_id"], "not": {"required": ["source"]}},
        {"required": ["source"], "not": {"anyOf": [
            {"required": ["entity_id"]}, {"required": ["sources"]},
        ]}},
    ]
    return schema


def is_mirror(config):
    return isinstance(config.get("source"), dict) and config["source"].get("kind") == "mirror"


def pair(position):
    return position["commit_seq"], position["entry_seq"]


@dataclass
class MirrorRange:
    mirror_id: str
    node_id: str
    after: dict
    through: dict
    source_ids: list


def open_range(node, hooks):
    mirror_id = node["config"]["source"]["mirror_id"]
    bound = hooks.capture_mirror_history(mirror_id=mirror_id)
    lower, upper = bound["lower_bound"], bound["upper_bound"]
    retained = pair(bound.get("retained_lower_bound", lower))
    sources = [bound["source_id"]]
    session = hooks.checkpoints
    durable = session.durable(node["id"], mirror_id)
    proposed = session.proposed(node["id"], mirror_id)
    for position in (durable, proposed):
        if position is not None and (
            not isinstance(position, MirrorCheckpointPosition)
            or position.history_epoch != bound["history_epoch"]
            or list(position.source_ids) != sources
            or not retained <= (position.commit_seq, position.entry_seq) <= pair(upper)
        ):
            raise MirrorCheckpointInvalid()
    candidates = (proposed,) if hooks.ignore_checkpoints else (durable, proposed)
    stored = max(
        (position for position in candidates if position is not None),
        key=lambda position: (position.commit_seq, position.entry_seq),
        default=None,
    )
    if stored is None and pair(lower) < retained:
        raise MirrorCheckpointInvalid()
    after = dict(lower) if stored is None else dict(
        mirror_id=mirror_id, history_epoch=stored.history_epoch,
        commit_seq=stored.commit_seq, entry_seq=stored.entry_seq,
    )
    return MirrorRange(mirror_id, node["id"], after, upper, sources)


def pages(opened, hooks, limit):
    after = opened.after
    remaining = limit
    while remaining > 0 and pair(after) < pair(opened.through):
        page = hooks.read_mirror_changes(
            mirror_id=opened.mirror_id, after=after,
            through=opened.through, limit=min(500, remaining),
        )
        next_position = page["next_position"]
        if (page.get("source_ids") != opened.source_ids
                or next_position.get("mirror_id") != opened.mirror_id
                or next_position.get("history_epoch") != opened.through["history_epoch"]
                or not pair(after) < pair(next_position) <= pair(opened.through)):
            raise MirrorCheckpointInvalid()
        entries = page["entries"]
        if len(entries) > min(500, remaining):
            raise MirrorCheckpointInvalid()
        previous = after
        for entry in entries:
            position = entry["position"]
            if (entry.get("origin") != "live" or position.get("mirror_id") != opened.mirror_id
                    or position.get("history_epoch") != opened.through["history_epoch"]
                    or not pair(previous) < pair(position) <= pair(next_position)):
                raise MirrorCheckpointInvalid()
            previous = position
        yield entries, next_position
        remaining -= len(entries) or 1
        after = next_position


def propose(opened, hooks, progress):
    if progress is not None:
        hooks.checkpoints.propose(opened.node_id, opened.mirror_id, MirrorCheckpointPosition(
            progress["history_epoch"], progress["commit_seq"], progress["entry_seq"],
            tuple(opened.source_ids),
        ))


def net(entries):
    groups = {}
    for entry in entries:
        key = json.dumps(entry["typed_key"], sort_keys=True, separators=(",", ":"))
        if key not in groups:
            groups[key] = [entry, entry]
        else:
            groups[key][1] = entry
    rows = []
    for first, last in groups.values():
        before, after = first["before"], last["after"]
        if before is None and after is None:
            continue
        operation = "insert" if before is None else "delete" if after is None else "update"
        rows.append({**last, "operation": operation, "before": before,
                     "first_position": first["position"], "last_position": last["position"]})
    return rows


def execute_read(node, hooks):
    opened = open_range(node, hooks)
    entries, progress = [], None
    for rows, position in pages(opened, hooks, int(node["config"].get("limit") or 1000)):
        entries.extend(rows)
        progress = position
    if node["config"].get("shape") == "net":
        entries = net(entries)
    propose(opened, hooks, progress)
    return dict(entries=entries, count=len(entries),
                has_more=pair(progress or opened.after) < pair(opened.through),
                last_position=progress, source_ids=opened.source_ids)
