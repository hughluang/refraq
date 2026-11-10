"""search_entities ranks the caller's serving read grants by cosine similarity."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

import pytest

os.environ["REFRAQ_STORE_BACKEND"] = "memory"
os.environ["REFRAQ_SECRETS_MASTER_KEY"] = "test-secrets-master-key"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("CELERY_BROKER_URL", "memory://")

from backend.admin.model_services.embeddings import EmbeddingSpace, EmbeddingVectors  # noqa: E402
from backend.admin.model_services.errors import ModelServiceTestFailed  # noqa: E402
from backend.admin.model_services.records import (  # noqa: E402
    CURRENT_PROCESSING_CONTRACT,
    ModelServiceRecord,
    PurposeState,
)
from backend.admin.model_services.store import (  # noqa: E402
    get_model_service_store,
    reset_model_service_store,
)
from backend.admin.role_store import get_role_store, reset_role_store  # noqa: E402
from backend.admin.roles import create_role, seed_roles  # noqa: E402
from backend.admin.security import hash_password  # noqa: E402
from backend.admin.subjects.service import add_member, create_group  # noqa: E402
from backend.admin.subjects.store import reset_subject_store  # noqa: E402
from backend.admin.token_store import generate_token_secret, get_token_store, reset_token_store  # noqa: E402
from backend.admin.user_store import get_user_store, reset_user_store  # noqa: E402
from backend.core.config import reset_settings_cache  # noqa: E402
from backend.core.time import utc_now  # noqa: E402
from backend.entity.access.records import GrantRecord, ProfileRecord  # noqa: E402
from backend.entity.access.store import get_access_store, reset_access_store  # noqa: E402
from backend.entity.embed_jobs.index_state import (  # noqa: E402
    publish_entity_index,
    reset_entity_index_store,
)
from backend.entity.ids import (  # noqa: E402
    new_access_grant_id,
    new_access_profile_id,
    new_attribute_id,
    new_version_id,
)
from backend.entity.lifecycle import latest_published_of  # noqa: E402
from backend.entity.mcp.actor import mcp_authorization  # noqa: E402
from backend.entity.mcp.catalog import MCP_TOOLS  # noqa: E402
from backend.entity.mcp.search import search_entities  # noqa: E402
from backend.entity.mcp.server import list_entities  # noqa: E402
from backend.entity.projection import (  # noqa: E402
    bind_entity_projection_drop_hook,
    canonical_text,
    reset_entity_projection_store,
    retain_projection,
)
from backend.entity.records import AttributeRecord, EntityVersionRecord  # noqa: E402
from backend.entity.service import create_entity  # noqa: E402
from backend.entity.store import get_entity_store, reset_entity_store  # noqa: E402
from backend.tags.api import replace_assignment  # noqa: E402
from backend.tags.service import create_tag  # noqa: E402
from backend.tags.store import reset_tag_store  # noqa: E402

_SERVICE_ID = "msvc_entity_search"
_SKU = AttributeRecord(
    name="sku",
    type="string",
    description="hidden-attribute-zz",
    max_length=32,
    required=True,
    unique=True,
)
_PAST = datetime(2020, 1, 1, tzinfo=timezone.utc)
_QUERY = [1.0, 0.0]
_MID_SCORE = 0.7071067811865476
_ROLE_SCORE = 0.8944271909999157
_GROUP_SCORE = 0.4472135954999579
_SUCCESSOR_SCORE = 0.9486832980505138


@dataclass
class World:
    secrets: dict[str, str]
    entities: dict[str, str]
    grants: dict[str, GrantRecord]
    tag_id: str


def _reset() -> None:
    reset_settings_cache()
    reset_user_store()
    reset_role_store()
    reset_token_store()
    reset_subject_store()
    reset_tag_store()
    reset_entity_store()
    reset_access_store()
    reset_entity_projection_store()
    reset_entity_index_store()
    reset_model_service_store()


def _pat(user_id: str) -> str:
    secret, prefix, token_hash = generate_token_secret()
    get_token_store().create(
        user_id=user_id,
        name="search",
        token_hash=token_hash,
        prefix=prefix,
        expires_at=utc_now() + timedelta(days=7),
    )
    return secret


def _user(account: str, role_id: str) -> str:
    user = get_user_store().create_user(
        account=account,
        display_name=account,
        password_hash=hash_password("secret"),
        role_id=role_id,
        status="active",
    )
    return user.id


def _publish(table_name: str, *, description: str | None = None) -> tuple[str, str]:
    saved = create_entity(
        table_name=table_name,
        name=table_name,
        description=description or f"Serving definition for {table_name}",
        attributes=[_SKU],
        actor_user_id=None,
        actor_token_id=None,
    )
    entity_id = str(saved["id"])
    current = get_entity_store().current_version(entity_id)
    assert current is not None
    attributes = [
        replace(attr, attribute_id=attr.attribute_id or new_attribute_id())
        for attr in current.attributes
    ]
    published = get_entity_store().save_version(
        replace(current, attributes=attributes, publish_status="published")
    )
    attribute_id = published.attributes[0].attribute_id
    assert isinstance(attribute_id, str) and attribute_id
    return entity_id, attribute_id


def _grant(
    entity_id: str,
    attribute_id: str,
    subject_type: str,
    subject_id: str,
    *,
    status: str = "active",
    valid_until: datetime | None = None,
) -> GrantRecord:
    now = utc_now()
    profile_id = new_access_profile_id()
    get_access_store().insert_profile(
        ProfileRecord(
            id=profile_id,
            entity_id=entity_id,
            key="clear",
            name="clear",
            description=None,
            columns=[{"attribute_id": attribute_id, "level": "clear"}],
            created_at=now,
            updated_at=now,
        )
    )
    record = GrantRecord(
        id=new_access_grant_id(),
        entity_id=entity_id,
        subject_type=subject_type,
        subject_id=subject_id,
        profile_id=profile_id,
        row_rule=None,
        actions=["read"],
        status=status,
        valid_until=valid_until,
        created_at=now,
        updated_at=now,
    )
    get_access_store().insert_grant(record)
    return record


def _seed_vector(entity_id: str, vector: tuple[float, ...]) -> None:
    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert head is not None
    text = canonical_text(entity_id)
    saved = retain_projection(
        entity_id=entity_id,
        head_version_id=head.id,
        content_hash=sha256(text.encode("utf-8")).hexdigest(),
        generation=1,
        processing_contract=CURRENT_PROCESSING_CONTRACT,
        embedding=vector,
        control_revision=1,
    )
    assert saved is not None


def _open_model(
    *,
    closed: bool = False,
    url: str = "http://embed.test/v1/embeddings",
    generation: int = 1,
    control_revision: int = 1,
    in_use: bool = True,
) -> None:
    now = utc_now()
    store = get_model_service_store()
    service_id = _SERVICE_ID if in_use else None
    if in_use:
        store.save(
            ModelServiceRecord(
                id=_SERVICE_ID,
                purpose="embedding",
                protocol="openai_compat",
                display_name="entity search",
                url=url,
                model="qwen-test",
                timeout_sec=30,
                batch_limit=32,
                secret="sk-test",
                created_at=now,
                updated_at=now,
            )
        )
    store.save_purpose(
        PurposeState(
            purpose="embedding",
            in_use_id=service_id,
            closed=closed,
            ready=False,
            generation=generation,
            control_revision=control_revision,
            processing_contract=CURRENT_PROCESSING_CONTRACT,
        )
    )


def _ready(**kwargs: Any) -> None:
    _open_model(**kwargs)
    assert publish_entity_index(
        generation=kwargs.get("generation", 1),
        control_revision=kwargs.get("control_revision", 1),
        written=1,
        attempted=1,
    )


def _install_embed(
    monkeypatch: pytest.MonkeyPatch,
    sink: list[list[str]] | None = None,
    *,
    vector: list[float] | None = None,
    before_return: Any = None,
    error: BaseException | None = None,
) -> None:
    def _fake(texts: list[str], **_kwargs: Any) -> EmbeddingVectors:
        if sink is not None:
            sink.append(list(texts))
        if before_return is not None:
            before_return()
        if error is not None:
            raise error
        return EmbeddingVectors(
            vectors=[list(vector or _QUERY)],
            space=EmbeddingSpace(
                service_id=_SERVICE_ID,
                generation=1,
                processing_contract=CURRENT_PROCESSING_CONTRACT,
            ),
        )

    monkeypatch.setattr("backend.entity.mcp.search.embed_texts", _fake)


def _call(secret: str | None, **kwargs: Any) -> dict[str, Any]:
    if secret is None:
        return json.loads(search_entities(**kwargs))
    with mcp_authorization(f"Bearer {secret}"):
        return json.loads(search_entities(**kwargs))


def _names(payload: dict[str, Any]) -> list[str]:
    return [item["table_name"] for item in payload["items"]]


@pytest.fixture()
def world() -> World:
    _reset()
    # A live drop hook enqueues an embed sweep. Eager execution in the suite
    # would replace the vectors this fixture just stored.
    bind_entity_projection_drop_hook(None)
    roles = get_role_store()
    seed_roles(roles)
    admin_role = roles.get_by_key("super_admin")
    assert admin_role is not None
    reader_role = create_role(
        roles,
        key="entity_search_reader",
        name="Entity search reader",
        permissions=["entity:data_read"],
    )
    author_role = create_role(
        roles,
        key="entity_search_author",
        name="Entity search author",
        permissions=["entity:data_read", "entity:write", "entity:access_manage"],
    )
    noread_role = create_role(
        roles,
        key="entity_search_noread",
        name="Entity search noread",
        permissions=["entity:write"],
    )
    admin_id = _user("search_admin", admin_role.id)
    reader_id = _user("search_reader", reader_role.id)
    author_id = _user("search_author", author_role.id)
    chief_id = _user("search_chief", admin_role.id)
    noread_id = _user("search_noread", noread_role.id)
    group = create_group(
        key="entity_search_east",
        name="Entity search east",
        description=None,
        actor_user_id=admin_id,
        actor_token_id=None,
    )
    add_member(group.id, reader_id, actor_user_id=admin_id, actor_token_id=None)
    tag = create_tag(
        name="Ledger",
        description="tag-gloss-zz",
        actor_user_id=admin_id,
        actor_token_id=None,
    )

    specs: tuple[tuple[str, tuple[float, ...] | None, str], ...] = (
        ("ent_alpha", (1.0, 0.0), "user"),
        ("ent_bravo", (1.0, 0.0), "user"),
        ("ent_successor", (3.0, 1.0), "user"),
        ("ent_role", (2.0, 1.0), "role"),
        ("ent_mid", (1.0, 1.0), "user"),
        ("ent_group", (1.0, 2.0), "group"),
        ("ent_flat", (0.0, 1.0), "user"),
        ("ent_flip", (-1.0, 0.0), "user"),
        ("ent_hidden", (1.0, 0.0), "none"),
        ("ent_disabled", (1.0, 0.0), "disabled"),
        ("ent_expired", (1.0, 0.0), "expired"),
        ("ent_old", (1.0, 0.0), "user"),
        ("ent_draft", None, "user"),
        ("ent_stale", (1.0, 0.0), "user"),
    )
    entities: dict[str, str] = {}
    grants: dict[str, GrantRecord] = {}
    _open_model()
    for table_name, vector, kind in specs:
        if table_name == "ent_draft":
            saved = create_entity(
                table_name=table_name,
                name=table_name,
                description="Draft definition",
                attributes=[_SKU],
                actor_user_id=None,
                actor_token_id=None,
            )
            entity_id = str(saved["id"])
            current = get_entity_store().current_version(entity_id)
            assert current is not None
            attribute_id = new_attribute_id()
            get_entity_store().save_version(
                replace(
                    current,
                    attributes=[replace(current.attributes[0], attribute_id=attribute_id)],
                )
            )
        else:
            entity_id, attribute_id = _publish(table_name)
        entities[table_name] = entity_id
        subject_type = "user"
        subject_id = reader_id
        status = "active"
        valid_until = None
        if kind == "role":
            subject_type = "role"
            subject_id = reader_role.id
        elif kind == "group":
            subject_type = "group"
            subject_id = group.id
        elif kind == "disabled":
            status = "disabled"
        elif kind == "expired":
            valid_until = _PAST
        elif kind == "none":
            subject_id = ""
        if kind != "none":
            grants[table_name] = _grant(
                entity_id,
                attribute_id,
                subject_type,
                subject_id,
                status=status,
                valid_until=valid_until,
            )
        if vector is not None:
            _seed_vector(entity_id, vector)

    successor = get_entity_store().current_version(entities["ent_successor"])
    assert successor is not None
    get_entity_store().create_version(
        EntityVersionRecord(
            id=new_version_id(),
            entity_id=entities["ent_successor"],
            version=successor.version + 1,
            attributes=list(successor.attributes),
            materialized_attributes=[],
            publish_status="publishing",
            latest_reconcile_job_id=None,
            created_at=successor.created_at,
            updated_at=successor.updated_at,
        )
    )
    stale = get_entity_store().get_entity(entities["ent_stale"])
    assert stale is not None
    get_entity_store().save_entity(
        replace(stale, description="renamed after the vector", updated_at=utc_now())
    )
    old = get_entity_store().get_entity(entities["ent_old"])
    assert old is not None
    get_entity_store().save_entity(
        replace(old, deprecated_at=utc_now(), updated_at=utc_now())
    )
    assigned = replace_assignment(
        kind="entity",
        subject_id=entities["ent_alpha"],
        base_revision=1,
        tag_ids=[],
        names=["Ledger"],
        actor_user_id=admin_id,
        actor_token_id=None,
    )
    _seed_vector(entities["ent_alpha"], (1.0, 0.0))
    built = World(
        secrets={
            "reader": _pat(reader_id),
            "author": _pat(author_id),
            "chief": _pat(chief_id),
            "noread": _pat(noread_id),
        },
        entities=entities,
        grants=grants,
        tag_id=assigned.tags[0].id,
    )
    yield built
    bind_entity_projection_drop_hook(None)
    _reset()


def test_search_entities_is_appended_after_the_existing_tools() -> None:
    assert [spec.name for spec in MCP_TOOLS] == [
        "list_entities",
        "describe_entity",
        "list_dictionary_codes",
        "get_row",
        "query_rows",
        "validate_sql",
        "run_sql",
        "search_entities",
    ]
    added = MCP_TOOLS[-1]
    assert added.permission == "entity:data_read"
    assert added.execution == "read"
    assert "query_text" in added.description
    assert "cosine" in added.description.lower()


def test_search_entities_rejects_blank_query_and_bad_limit(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()
    sink: list[list[str]] = []
    _install_embed(monkeypatch, sink)
    for query_text in ("", "   ", "\n\t"):
        payload = _call(world.secrets["reader"], query_text=query_text)
        assert payload["error"]["code"] == "REQUEST_INVALID"
        assert payload["error"]["message"] == "query_text is required"
    too_long = _call(world.secrets["reader"], query_text="a" * 2001)
    assert too_long["error"]["code"] == "REQUEST_INVALID"
    assert too_long["error"]["message"] == "query_text must be at most 2000 characters"
    for limit in (0, 51, -3, True, 1.5):
        payload = _call(world.secrets["reader"], query_text="ledger", limit=limit)
        assert payload["error"]["code"] == "REQUEST_INVALID", limit
        assert payload["error"]["message"] == "limit must be an integer from 1 through 50"
    assert sink == []
    boundary = _call(world.secrets["reader"], query_text="b" * 2000, limit=1)
    assert set(boundary) == {"items"}
    assert sink == [["b" * 2000]]


def test_search_entities_ranks_readable_serving_rows_by_cosine(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()
    sink: list[list[str]] = []
    _install_embed(monkeypatch, sink)
    payload = _call(world.secrets["reader"], query_text="  zzzz-not-a-name  ")
    assert set(payload) == {"items"}
    assert _names(payload) == [
        "ent_alpha",
        "ent_bravo",
        "ent_successor",
        "ent_role",
        "ent_mid",
        "ent_group",
        "ent_flat",
        "ent_flip",
    ]
    by_name = {item["table_name"]: item for item in payload["items"]}
    assert by_name["ent_alpha"]["score"] == 1.0
    assert by_name["ent_bravo"]["score"] == 1.0
    assert by_name["ent_successor"]["score"] == pytest.approx(_SUCCESSOR_SCORE)
    assert by_name["ent_role"]["score"] == pytest.approx(_ROLE_SCORE)
    assert by_name["ent_mid"]["score"] == pytest.approx(_MID_SCORE)
    assert by_name["ent_group"]["score"] == pytest.approx(_GROUP_SCORE)
    assert by_name["ent_flat"]["score"] == 0.0
    assert by_name["ent_flip"]["score"] == -1.0
    alpha = by_name["ent_alpha"]
    assert set(alpha) == {"table_name", "name", "description", "tags", "score"}
    assert alpha["name"] == "ent_alpha"
    assert alpha["description"] == "Serving definition for ent_alpha"
    assert alpha["tags"] == [{"id": world.tag_id, "name": "Ledger"}]
    assert by_name["ent_bravo"]["tags"] == []
    assert sink == [["zzzz-not-a-name"]]
    assert "hidden-attribute-zz" not in sink[0][0]
    assert "tag-gloss-zz" not in sink[0][0]

    same = _call(world.secrets["reader"], query_text="alpha")
    assert _names(same) == _names(payload)
    topped = _call(world.secrets["reader"], query_text="alpha", limit=1)
    assert _names(topped) == ["ent_alpha"]
    assert set(topped) == {"items"}


def test_search_entities_default_limit_is_ten_without_backfill_fields(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()
    _install_embed(monkeypatch, [])
    roles = get_role_store()
    cap_role = create_role(
        roles,
        key="entity_search_cap",
        name="Entity search cap",
        permissions=["entity:data_read"],
    )
    cap_id = _user("search_cap", cap_role.id)
    secret = _pat(cap_id)
    for index in range(1, 13):
        entity_id, attribute_id = _publish(f"cap_{index:02d}")
        _grant(entity_id, attribute_id, "user", cap_id)
        _seed_vector(entity_id, (float(index), 1.0))
    payload = _call(secret, query_text="cap")
    assert _names(payload) == [f"cap_{index:02d}" for index in range(12, 2, -1)]
    assert "cap_02" not in _names(payload)
    assert "cap_01" not in _names(payload)
    assert "ent_alpha" not in _names(payload)
    exact = _call(secret, query_text="cap", limit=50)
    assert _names(exact) == [f"cap_{index:02d}" for index in range(12, 0, -1)]
    assert set(exact) == {"items"}
    del world


def test_permissions_and_ineffective_grants_add_no_rows(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()
    sink: list[list[str]] = []
    _install_embed(monkeypatch, sink)
    author = _call(world.secrets["author"], query_text="alpha")
    chief = _call(world.secrets["chief"], query_text="alpha")
    assert author == {"items": []}
    assert chief == {"items": []}
    assert sink == []

    bare = _call(None, query_text="alpha")
    assert bare["error"]["code"] == "AUTH_UNAUTHENTICATED"
    forbidden = _call(world.secrets["noread"], query_text="alpha")
    assert forbidden["error"] == {
        "code": "AUTH_FORBIDDEN",
        "message": "Missing permission entity:data_read",
    }


def test_stale_deprecated_and_hidden_edits_do_not_change_the_rank(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()
    _install_embed(monkeypatch, [])
    with mcp_authorization(f"Bearer {world.secrets['reader']}"):
        listed = json.loads(list_entities())
    assert "ent_stale" in _names(listed)
    assert "ent_old" not in _names(listed)
    assert "ent_draft" not in _names(listed)
    first = _call(world.secrets["reader"], query_text="rank")
    assert "ent_stale" not in _names(first)
    assert "ent_old" not in _names(first)
    assert "ent_draft" not in _names(first)
    assert "ent_hidden" not in _names(first)
    assert "ent_disabled" not in _names(first)
    assert "ent_expired" not in _names(first)
    version = get_entity_store().current_version(world.entities["ent_flat"])
    assert version is not None
    hidden = replace(version.attributes[0], description="edited-hidden-attribute-zz")
    get_entity_store().save_version(replace(version, attributes=[hidden]))
    second = _call(world.secrets["reader"], query_text="rank")
    assert _names(second) == _names(first)
    assert [item["score"] for item in second["items"]] == [
        item["score"] for item in first["items"]
    ]


def test_empty_authorized_set_does_not_call_the_model(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()
    sink: list[list[str]] = []
    _install_embed(monkeypatch, sink)
    assert _call(world.secrets["author"], query_text="alpha") == {"items": []}
    assert sink == []


def test_model_and_index_failures_are_not_an_empty_page(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    sink: list[list[str]] = []
    _install_embed(monkeypatch, sink)
    reset_model_service_store()
    missing = _call(world.secrets["reader"], query_text="alpha")
    assert missing["error"]["code"] == "MODEL_SERVICE_NOT_IN_USE"
    assert "ent_hidden" not in missing["error"]["message"]

    _open_model(url="")
    no_url = _call(world.secrets["reader"], query_text="alpha")
    assert no_url["error"]["code"] == "MODEL_SERVICE_ENDPOINT_MISSING"

    _open_model(closed=True)
    closed = _call(world.secrets["author"], query_text="alpha")
    assert closed["error"]["code"] == "MODEL_SERVICE_CLOSED"
    assert closed["error"]["message"] == "Model Service is closed"

    _open_model()
    not_ready = _call(world.secrets["reader"], query_text="alpha")
    assert not_ready["error"]["code"] == "ENTITY_INDEX_NOT_READY"
    assert not_ready["error"]["message"] == "Entity index is not ready"
    assert "ent_hidden" not in json.dumps(not_ready)

    _ready()
    store = get_model_service_store()
    state = store.get_purpose("embedding")
    store.save_purpose(replace(state, generation=state.generation + 1))
    shifted = _call(world.secrets["reader"], query_text="alpha")
    assert shifted["error"]["code"] == "ENTITY_INDEX_NOT_READY"
    assert sink == []


def test_model_call_failure_hides_provider_diagnostics(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()
    sink: list[list[str]] = []
    _install_embed(
        monkeypatch,
        sink,
        error=ModelServiceTestFailed(
            "Unusable embeddings response from http://embed.test/v1/embeddings "
            "secret sk-test query warehouse-secret-zz"
        ),
    )
    payload = _call(world.secrets["reader"], query_text="warehouse-secret-zz")
    assert payload["error"]["code"] == "ENTITY_SEARCH_EMBED_FAILED"
    assert payload["error"]["message"] == "Entity search query embed failed"
    text = json.dumps(payload)
    assert "embed.test" not in text
    assert "sk-test" not in text
    assert "warehouse-secret-zz" not in text
    assert "ent_hidden" not in text


def test_revoke_during_the_call_shortens_the_page_without_backfill(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()

    def _revoke() -> None:
        grant = world.grants["ent_alpha"]
        get_access_store().update_grant(replace(grant, status="disabled"))

    _install_embed(monkeypatch, [], before_return=_revoke)
    payload = _call(world.secrets["reader"], query_text="alpha", limit=2)
    assert _names(payload) == ["ent_bravo"]


def test_definition_change_during_the_call_drops_the_stale_row(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()

    def _rename() -> None:
        from backend.entity.projection import drop_entity_projection

        entity = get_entity_store().get_entity(world.entities["ent_alpha"])
        assert entity is not None
        get_entity_store().save_entity(
            replace(entity, description="changed during search", updated_at=utc_now())
        )
        drop_entity_projection(entity.id)

    _install_embed(monkeypatch, [], before_return=_rename)
    payload = _call(world.secrets["reader"], query_text="alpha", limit=2)
    assert _names(payload) == ["ent_bravo"]


def test_control_revision_change_during_the_call_fails_the_search(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()

    def _bump() -> None:
        store = get_model_service_store()
        state = store.get_purpose("embedding")
        store.save_purpose(replace(state, control_revision=state.control_revision + 1))

    _install_embed(monkeypatch, [], before_return=_bump)
    payload = _call(world.secrets["reader"], query_text="warehouse-secret-zz")
    assert payload["error"]["code"] == "MODEL_SERVICE_CONTROL_REVISION_MISMATCH"
    assert "warehouse-secret-zz" not in payload["error"]["message"]
    assert "items" not in payload


def test_search_does_not_enter_admission(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready()
    _install_embed(monkeypatch, [])

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("search entered admission")

    monkeypatch.setattr("backend.core.admission.await_admitted", _boom)
    import backend.entity.mcp.search as search_mod

    if hasattr(search_mod, "await_admitted"):
        monkeypatch.setattr(search_mod, "await_admitted", _boom)
    payload = _call(world.secrets["reader"], query_text="alpha", limit=1)
    assert _names(payload) == ["ent_alpha"]
