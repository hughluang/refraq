"""Write compatibility: one rule for a match key, a mapping, and a head."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.channel.graph import validate
from backend.channel.nodes import list_node_types
from backend.channel.nodes.spec import ResolvedAttribute, ResolvedEntity
from backend.channel.store import ChannelRecord, get_channel_store
from backend.tests.channel_hooks_fake import FakeHooks
from backend.channel.write_compatibility import write_reasons
from backend.channel.write_targets import incompatible_writers
from backend.core.time import utc_now


def _attr(
    name: str,
    *,
    unique: bool = False,
    business_key: bool = False,
) -> ResolvedAttribute:
    return ResolvedAttribute(name=name, unique=unique, business_key=business_key)


def _head(*attributes: ResolvedAttribute) -> ResolvedEntity:
    return ResolvedEntity(attributes=attributes)


SKU = _attr("sku", unique=True, business_key=True)
NAME = _attr("name")
ROW = _attr("row_id", unique=True)


@pytest.mark.parametrize(
    ("match_key", "mapping", "head", "expected"),
    [
        (
            "row_id",
            [{"attribute": "sku", "key": "sku"}],
            _head(SKU, NAME),
            [("attribute_missing", "match_key")],
        ),
        (
            "row_id",
            [{"attribute": "sku", "key": "sku"}],
            _head(ROW, SKU),
            [("attribute_missing", "match_key")],
        ),
        (
            None,
            [{"attribute": "sku", "key": "sku"}],
            _head(_attr("sku", unique=True), NAME),
            [("business_key_missing", "match_key")],
        ),
        (
            None,
            [{"attribute": "sku", "key": "sku"}],
            _head(SKU, NAME),
            [],
        ),
        (
            None,
            [{"attribute": "sku", "key": "sku"}],
            _head(_attr("sku", business_key=True), NAME),
            [("match_key_not_unique", "match_key")],
        ),
        (
            "missing",
            [{"attribute": "sku", "key": "sku"}],
            _head(SKU, NAME),
            [("attribute_missing", "match_key")],
        ),
        (
            "name",
            [{"attribute": "sku", "key": "sku"}],
            _head(SKU, NAME),
            [("match_key_not_unique", "match_key")],
        ),
        (
            "sku",
            [{"attribute": "gone", "key": "gone"}],
            _head(SKU, NAME),
            [("attribute_missing", "gone")],
        ),
        (
            "gone",
            [
                {"attribute": "gone", "key": "gone"},
                {"attribute": "sku", "key": "sku"},
                {"attribute": "gone", "key": "again"},
                {"attribute": "other", "key": "other"},
            ],
            _head(SKU, NAME),
            [
                ("attribute_missing", "match_key"),
                ("attribute_missing", "gone"),
                ("attribute_missing", "other"),
            ],
        ),
    ],
)
def test_write_reasons(
    match_key: str | None,
    mapping: list[dict[str, str]],
    head: ResolvedEntity,
    expected: list[tuple[str, str]],
) -> None:
    reasons = write_reasons(match_key, mapping, head)
    assert [(reason.code, reason.subject) for reason in reasons] == expected


# The same write and the same head, including an attribute literally named row_id.
ENTITY_ID = "ent_dst"
AGREED_HEAD = _head(ROW, SKU)
AGREED_MAPPING = [
    {"attribute": "sku", "key": "sku"},
    {"attribute": "gone", "key": "gone"},
]
AGREED_CODES = ["attribute_missing"]


def _write_config(on_incompatible_head: str = "fail") -> dict[str, object]:
    return {
        "entity_id": ENTITY_ID,
        "mode": "upsert",
        "match_key": "row_id",
        "source": '[{"sku": "a"}]',
        "mapping": AGREED_MAPPING,
        "on_incompatible_head": on_incompatible_head,
    }


class _Resolver:
    def entity_head(self, entity_id: str) -> ResolvedEntity | None:
        return AGREED_HEAD if entity_id == ENTITY_ID else None

    def channel_exists(self, channel_id: str) -> bool:
        del channel_id
        return False

    def published_trigger_type(self, channel_id: str) -> str | None:
        del channel_id
        return None

    def source_exists(self, source_id: str) -> bool:
        del source_id
        return False


def _node(node_id: str, type_id: str, name: str, config: dict | None = None) -> dict:
    return {
        "id": node_id,
        "ref": node_id.removeprefix("nd_"),
        "type": type_id,
        "name": name,
        "position": {"x": 0, "y": 0},
        "config": {} if config is None else config,
        "on_error": "stop",
        "retry": None,
    }


def test_publish_validation_reports_the_match_key_reason() -> None:
    graph = {
        "nodes": [
            _node("nd_trigger", "trigger.manual", "Run"),
            _node("nd_write", "write.entity", "Write materials", _write_config()),
        ],
        "edges": [
            {
                "id": "ed_1",
                "source": {"node_id": "nd_trigger", "port": "main"},
                "target": {"node_id": "nd_write", "port": "main"},
            }
        ],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }
    problems = [
        problem
        for problem in validate(graph, _Resolver())
        if problem.code == "CHANNEL_MATCH_KEY_INVALID"
    ]
    assert [(problem.code, problem.detail, problem.node_id) for problem in problems] == [
        ("CHANNEL_MATCH_KEY_INVALID", "Match key does not resolve", "nd_write")
    ]


def test_write_node_fails_or_skips_with_the_same_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.channel.nodes.write.entity.head_target",
        lambda entity_id: SimpleNamespace(
            attributes=tuple(
                SimpleNamespace(
                    name=attr.name,
                    unique=attr.unique,
                    business_key=attr.business_key,
                    type=attr.value_type,
                )
                for attr in AGREED_HEAD.attributes
            )
        ),
    )
    execute = next(item.execute for item in list_node_types() if item.type_id == "write.entity")
    failed = execute(
        _node("nd_write", "write.entity", "Write materials", _write_config("fail")),
        FakeHooks(),
    )
    assert failed.status == "failed"
    assert failed.error_code == "CHANNEL_WRITE_INCOMPATIBLE"
    assert failed.error_detail == {"reasons": AGREED_CODES}

    skipped = execute(
        _node("nd_write", "write.entity", "Write materials", _write_config("skip")),
        FakeHooks(),
    )
    assert skipped.status == "skipped"
    assert skipped.output == {"skipped": True, "reasons": AGREED_CODES}


def test_publish_preview_lists_the_same_codes() -> None:
    now = utc_now()
    store = get_channel_store()
    created = store.create(
        ChannelRecord(
            id="chn_write",
            name="Materials",
            description=None,
            active=False,
            draft_graph={"nodes": [], "edges": [], "settings": {}},
            draft_revision=1,
            draft_updated_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    graph = {
        "nodes": [
            _node("nd_write", "write.entity", "Write materials", _write_config())
        ],
        "edges": [],
        "settings": {"run_timeout_sec": None, "error_channel_id": None},
    }
    stored = store.replace_draft(
        created.id,
        base_revision=created.draft_revision,
        graph=graph,
        now=now,
    )
    store.publish_version(
        created.id,
        draft_revision=stored.draft_revision,
        published_at=now,
        published_by_user_id="user_admin",
    )
    attributes = [
        {
            "name": attr.name,
            "type": attr.value_type,
            "unique": attr.unique,
            "business_key": attr.business_key,
            "required": False,
        }
        for attr in AGREED_HEAD.attributes
    ]
    found = incompatible_writers(ENTITY_ID, attributes)
    assert [item["reasons"] for item in found] == [AGREED_CODES]

    objects = [
        SimpleNamespace(
            name=attr.name,
            unique=attr.unique,
            business_key=attr.business_key,
            required=False,
        )
        for attr in AGREED_HEAD.attributes
    ]
    assert [item["reasons"] for item in incompatible_writers(ENTITY_ID, objects)] == [
        AGREED_CODES
    ]
