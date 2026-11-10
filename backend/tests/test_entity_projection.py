"""Entity embedding projection: canonical text, identity, and immediate ineligibility."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, text

from backend.admin.model_services.records import ModelServiceRecord, PurposeState
from backend.admin.model_services.store import get_model_service_store
from backend.core.time import utc_now
from backend.entity.dictionaries.service import create_dictionary
from backend.entity.ids import new_version_id
from backend.entity.records import AttributeRecord, EntityVersionRecord
from backend.entity.lifecycle import latest_published_of
from backend.entity.service import (
    create_entity,
    deprecate_entity,
    open_version,
    patch_entity,
    replace_entity_tags,
)
from backend.entity.store import get_entity_store
from backend.tags.service import create_tag

_SKU = AttributeRecord(name="sku", type="string", max_length=32, required=True, unique=True)
_INTEGRATION_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq_test",
)
_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
_MIGRATED = False
_SERVING_HASH = "a20f19b9562d5bd6942eb8ce6e7780437d7f7134b9ca211df12ebf10247c823e"
_RENAMED_HASH = "3d23db15f6e8527a7f6ea43c57c312852efe7901976c9f6d71545a0c0c4da621"
_CONTRACT = "prefix-1024-l2-v1"


def _entity_with_excluded_detail() -> str:
    dictionary = create_dictionary(
        name="kinds",
        display_name="Kinds",
        description="dictionary gloss zz",
        entries=[{"code": "hidden_code_zz", "label": "hidden label zz", "active": True}],
        actor_user_id=None,
        actor_token_id=None,
    )
    zulu = create_tag(
        name="Zulu",
        description="tag gloss zz",
        actor_user_id=None,
        actor_token_id=None,
    )
    alpha = create_tag(
        name="alpha",
        description="other gloss zz",
        actor_user_id=None,
        actor_token_id=None,
    )
    saved = create_entity(
        table_name="materials",
        name="Material",
        description="A stock item",
        attributes=[
            AttributeRecord(
                name="sku",
                type="string",
                description="column gloss zz",
                max_length=32,
            ),
            AttributeRecord(
                name="kind",
                type="dictionary",
                dictionary_id=dictionary["id"],
            ),
            AttributeRecord(name="parent", type="reference", target_entity_id="self"),
        ],
        actor_user_id=None,
        actor_token_id=None,
        tag_ids=[zulu.id, alpha.id],
    )
    return str(saved["id"])


def _seed_embedding(*, generation: int, closed: bool = False) -> None:
    now = utc_now()
    store = get_model_service_store()
    store.save(
        ModelServiceRecord(
            id="msvc_entity_projection",
            purpose="embedding",
            protocol="openai_compat",
            display_name="projection test",
            url="http://embed.test/v1/embeddings",
            model="qwen-test",
            timeout_sec=45,
            batch_limit=32,
            secret="sk-test-credential",
            created_at=now,
            updated_at=now,
        )
    )
    store.save_purpose(
        PurposeState(
            purpose="embedding",
            in_use_id="msvc_entity_projection",
            closed=closed,
            ready=False,
            generation=generation,
            control_revision=0,
            processing_contract=_CONTRACT,
        )
    )


def _writer():
    from backend.admin.roles import seed_roles
    from backend.admin.role_store import get_role_store
    from backend.admin.security import hash_password
    from backend.admin.user_store import get_user_store

    roles = get_role_store()
    seed_roles(roles)
    admin = roles.get_by_key("super_admin")
    assert admin is not None
    return get_user_store().create_user(
        account=f"projection_{uuid.uuid4().hex[:12]}",
        display_name="Writer",
        password_hash=hash_password("secret"),
        role_id=admin.id,
        status="active",
    )


def _postgres_available() -> bool:
    try:
        engine = create_engine(_MAINTENANCE_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


def _migrate_once() -> None:
    global _MIGRATED
    if _MIGRATED:
        return
    # 0087 also widens version_num inside upgrade(). Doing it here first lets a
    # database whose stamp is still varchar(32) reach that revision.
    engine = create_engine(_INTEGRATION_DATABASE_URL)
    with engine.begin() as conn:
        present = conn.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar()
        if present:
            conn.execute(
                text(
                    "ALTER TABLE alembic_version "
                    "ALTER COLUMN version_num TYPE varchar(64)"
                )
            )
    engine.dispose()
    from backend.core.entry import migrate_with_advisory_lock

    migrate_with_advisory_lock(_INTEGRATION_DATABASE_URL)
    _MIGRATED = True


@pytest.fixture(autouse=True, params=["memory", "sql"])
def projection_backend(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Exercise the memory adapter and the metadata-database table."""

    from backend.admin.audit_store import reset_audit_store
    from backend.admin.model_services.records import PurposeState
    from backend.admin.model_services.store import (
        get_model_service_store,
        reset_model_service_store,
    )
    from backend.admin.role_store import reset_role_store
    from backend.admin.user_store import reset_user_store
    from backend.core.config import reset_settings_cache
    from backend.core.db import reset_db_singletons
    from backend.entity.access.store import reset_access_store
    from backend.entity.dictionaries.store import reset_dictionary_store
    from backend.entity.projection import reset_entity_projection_store
    from backend.entity.store import reset_entity_store
    from backend.entity.table_port import (
        RecordingEntityTablePort,
        bind_entity_table_port,
    )
    from backend.jobs.store import reset_job_store
    from backend.tags.store import reset_tag_store

    reset_tag_store()
    reset_dictionary_store()
    reset_entity_projection_store()
    if request.param == "memory":
        yield request.param
        reset_entity_projection_store()
        return
    if not _postgres_available():
        pytest.skip("Postgres not available (start: docker compose up -d)")
    _migrate_once()
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
    monkeypatch.setenv("DATABASE_URL", _INTEGRATION_DATABASE_URL)
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    reset_settings_cache()
    reset_db_singletons()
    reset_entity_store()
    reset_tag_store()
    reset_dictionary_store()
    reset_job_store()
    reset_access_store()
    reset_audit_store()
    reset_model_service_store()
    reset_user_store()
    reset_role_store()
    reset_entity_projection_store()
    bind_entity_table_port(RecordingEntityTablePort())
    engine = create_engine(_INTEGRATION_DATABASE_URL)
    with engine.begin() as conn:
        present = [
            name
            for name in (
                "entity_embeddings",
                "entity_versions",
                "business_entities",
                "tag_assignments",
                "tag_subject_revisions",
                "tags",
                "dictionary_entries",
                "dictionaries",
            )
            if conn.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{name}"},
            ).scalar()
        ]
        if present:
            conn.execute(
                text(
                    "TRUNCATE TABLE "
                    + ", ".join(present)
                    + " RESTART IDENTITY CASCADE"
                )
            )
    engine.dispose()
    get_model_service_store().save_purpose(
        PurposeState(
            purpose="embedding",
            in_use_id=None,
            closed=False,
            ready=False,
            generation=0,
            control_revision=0,
            processing_contract=_CONTRACT,
        )
    )
    yield request.param
    reset_entity_projection_store()
    reset_settings_cache()
    reset_db_singletons()


def _serving_entity(
    *,
    table_name: str = "materials",
    name: str = "Material",
    description: str = "A stock item",
    tag_ids: list[str] | None = None,
) -> tuple[str, str]:
    saved = create_entity(
        table_name=table_name,
        name=name,
        description=description,
        attributes=[_SKU],
        actor_user_id=None,
        actor_token_id=None,
        tag_ids=tag_ids,
    )
    entity_id = str(saved["id"])
    current = get_entity_store().current_version(entity_id)
    assert current is not None
    published = get_entity_store().save_version(
        replace(current, publish_status="published")
    )
    return entity_id, published.id


def _next_published_head(entity_id: str) -> str:
    store = get_entity_store()
    current = store.current_version(entity_id)
    assert current is not None
    saved = store.create_version(
        EntityVersionRecord(
            id=new_version_id(),
            entity_id=entity_id,
            version=current.version + 1,
            attributes=list(current.attributes),
            materialized_attributes=[],
            publish_status="published",
            latest_reconcile_job_id=None,
            created_at=current.created_at,
            updated_at=current.updated_at,
        )
    )
    return saved.id


def test_definition_text_is_table_name_name_description_then_tag_names() -> None:
    from backend.entity.projection import definition_text

    assert (
        definition_text(
            table_name="materials",
            name="Material",
            description="A stock item",
            tag_names=("alpha", "Zulu"),
        )
        == "materials\nMaterial\nA stock item\nalpha\nZulu"
    )


def test_definition_text_omits_blank_parts() -> None:
    from backend.entity.projection import definition_text

    assert (
        definition_text(
            table_name="materials",
            name="Material",
            description="   ",
            tag_names=(" ", "alpha"),
        )
        == "materials\nMaterial\nalpha"
    )


def _table_exists(name: str) -> bool:
    engine = create_engine(_INTEGRATION_DATABASE_URL)
    try:
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    text("SELECT to_regclass(:name) IS NOT NULL"),
                    {"name": f"public.{name}"},
                ).scalar()
            )
    finally:
        engine.dispose()


def test_canonical_text_orders_tag_names_and_omits_everything_else(
    projection_backend: str,
) -> None:
    from backend.entity.projection import canonical_text

    if projection_backend == "sql" and not _table_exists("dictionaries"):
        pytest.skip("integration database is missing dictionaries")
    entity_id = _entity_with_excluded_detail()
    text = canonical_text(entity_id)
    assert text == "materials\nMaterial\nA stock item\nalpha\nZulu"
    assert "column gloss zz" not in text
    assert "hidden_code_zz" not in text
    assert "hidden label zz" not in text
    assert "dictionary gloss zz" not in text
    assert "tag gloss zz" not in text
    assert "sku" not in text
    assert entity_id not in text


def test_current_row_records_head_hash_generation_and_contract() -> None:
    from backend.entity.projection import current_projection, retain_projection

    entity_id, head_id = _serving_entity()
    saved = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert saved is not None
    assert saved.entity_id == entity_id
    assert saved.head_version_id == head_id
    assert saved.content_hash == _SERVING_HASH
    assert saved.generation == 5
    assert saved.processing_contract == _CONTRACT
    assert saved.embedding == (1.0, 0.0)
    assert current_projection(entity_id) == saved


def test_a_write_for_an_older_head_does_not_become_current() -> None:
    from backend.entity.projection import current_projection, retain_projection

    entity_id, first_head = _serving_entity()
    second_head = _next_published_head(entity_id)
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=second_head,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None
    refused = retain_projection(
        entity_id=entity_id,
        head_version_id=first_head,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(0.0, 1.0),
    )
    assert refused is None
    current = current_projection(entity_id)
    assert current is not None
    assert current.head_version_id == second_head
    assert current.embedding == (1.0, 0.0)


def test_a_write_for_an_older_hash_does_not_become_current() -> None:
    from backend.entity.projection import current_projection, retain_projection

    entity_id, head_id = _serving_entity()
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None
    refused = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_RENAMED_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(0.0, 1.0),
    )
    assert refused is None
    current = current_projection(entity_id)
    assert current is not None
    assert current.content_hash == _SERVING_HASH
    assert current.embedding == (1.0, 0.0)


def test_a_write_for_an_older_generation_does_not_become_current() -> None:
    from backend.entity.projection import current_projection, retain_projection

    entity_id, head_id = _serving_entity()
    _seed_embedding(generation=5)
    assert (
        retain_projection(
            entity_id=entity_id,
            head_version_id=head_id,
            content_hash=_SERVING_HASH,
            generation=4,
            processing_contract=_CONTRACT,
            embedding=(0.0, 1.0),
        )
        is None
    )
    assert current_projection(entity_id) is None
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None
    assert (
        retain_projection(
            entity_id=entity_id,
            head_version_id=head_id,
            content_hash=_SERVING_HASH,
            generation=4,
            processing_contract=_CONTRACT,
            embedding=(0.0, 1.0),
        )
        is None
    )
    current = current_projection(entity_id)
    assert current is not None
    assert current.generation == 5
    assert current.embedding == (1.0, 0.0)


def test_a_write_for_another_processing_contract_does_not_become_current() -> None:
    from backend.entity.projection import current_projection, retain_projection

    entity_id, head_id = _serving_entity()
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None
    refused = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract="other-contract",
        embedding=(0.0, 1.0),
    )
    assert refused is None
    current = current_projection(entity_id)
    assert current is not None
    assert current.processing_contract == _CONTRACT
    assert current.embedding == (1.0, 0.0)


def test_renaming_a_serving_entity_drops_the_vector_while_the_model_is_closed(
    monkeypatch,
) -> None:
    from backend.admin.model_services import openai_compat
    from backend.entity.projection import current_projection, retain_projection

    entity_id, head_id = _serving_entity()
    _seed_embedding(generation=5, closed=True)
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None

    def _urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("authoring called the embedding endpoint")

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    open_version(
        entity_id=entity_id,
        attributes=None,
        actor_user_id=None,
        actor_token_id=None,
    )
    assert current_projection(entity_id) is not None
    saved = patch_entity(
        entity_id=entity_id,
        name="Renamed",
        description=None,
        actor_user_id=None,
        actor_token_id=None,
    )
    assert saved["name"] == "Renamed"
    assert current_projection(entity_id) is None
    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert head is not None
    assert head.id == head_id


def test_changing_the_description_drops_the_vector_when_no_model_is_configured() -> None:
    from backend.entity.projection import current_projection, retain_projection

    entity_id, head_id = _serving_entity()
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None
    open_version(
        entity_id=entity_id,
        attributes=None,
        actor_user_id=None,
        actor_token_id=None,
    )
    saved = patch_entity(
        entity_id=entity_id,
        name=None,
        description="Updated stock",
        actor_user_id=None,
        actor_token_id=None,
    )
    assert saved["description"] == "Updated stock"
    assert current_projection(entity_id) is None


def test_replacing_tags_drops_the_vector_without_calling_the_model() -> None:
    from backend.entity.projection import current_projection, retain_projection

    entity_id, head_id = _serving_entity()
    before = get_entity_store().get_entity(entity_id)
    assert before is not None
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None
    tag = create_tag(
        name="alpha",
        description="tag gloss zz",
        actor_user_id=None,
        actor_token_id=None,
    )
    replaced = replace_entity_tags(
        entity_id=entity_id,
        base_revision=1,
        tag_ids=[tag.id],
        names=[],
        actor_user_id=None,
        actor_token_id=None,
        user=_writer(),
    )
    assert replaced["tags"] == [{"id": tag.id, "name": "alpha"}]
    after = get_entity_store().get_entity(entity_id)
    assert after is not None
    assert after.updated_at == before.updated_at
    assert current_projection(entity_id) is None


def test_renaming_a_tag_drops_every_using_entity_without_bumping_timestamps() -> None:
    from backend.entity.projection import current_projection, retain_projection
    from backend.tags.api import KIND_ENTITY, read_assignment
    from backend.tags.service import update_tag

    tag = create_tag(
        name="alpha",
        description="tag gloss zz",
        actor_user_id=None,
        actor_token_id=None,
    )
    materials_id, materials_head = _serving_entity(tag_ids=[tag.id])
    vendors_id, vendors_head = _serving_entity(
        table_name="vendors",
        name="Vendor",
        description="A supplier",
        tag_ids=[tag.id],
    )
    places_id, places_head = _serving_entity(
        table_name="places",
        name="Place",
        description="A site",
    )
    assert (
        retain_projection(
            entity_id=materials_id,
            head_version_id=materials_head,
            content_hash="b63a08c2c86b426233a6dd2e6f78199087e9580493ec0e2cec3a4c24fe38f590",
            generation=5,
            processing_contract=_CONTRACT,
            embedding=(1.0, 0.0),
        )
        is not None
    )
    assert (
        retain_projection(
            entity_id=vendors_id,
            head_version_id=vendors_head,
            content_hash="3d3efedfdccc46b4aab73fe12bfe8ff5d196e9a7da39428efd429967dc04d43b",
            generation=5,
            processing_contract=_CONTRACT,
            embedding=(0.0, 1.0),
        )
        is not None
    )
    assert (
        retain_projection(
            entity_id=places_id,
            head_version_id=places_head,
            content_hash="c889d88f75bca88d23a8e9bc18876685e1b55ce0658bc50be16be453d1fd1533",
            generation=5,
            processing_contract=_CONTRACT,
            embedding=(0.0, 0.0, 1.0),
        )
        is not None
    )
    before = get_entity_store().get_entity(materials_id)
    assert before is not None
    revision = read_assignment(KIND_ENTITY, materials_id).tag_revision
    renamed = update_tag(
        tag.id,
        name="Alpha Prime",
        name_set=True,
        description=None,
        description_set=False,
        actor_user_id=None,
        actor_token_id=None,
    )
    assert renamed.name == "Alpha Prime"
    after = get_entity_store().get_entity(materials_id)
    assert after is not None
    assert after.updated_at == before.updated_at
    assert read_assignment(KIND_ENTITY, materials_id).tag_revision == revision
    assert current_projection(materials_id) is None
    assert current_projection(vendors_id) is None
    assert current_projection(places_id) is not None
    assert current_projection(places_id).embedding == (0.0, 0.0, 1.0)


def test_editing_a_tag_description_keeps_the_entity_vector() -> None:
    from backend.entity.projection import current_projection, retain_projection
    from backend.tags.service import update_tag

    tag = create_tag(
        name="alpha",
        description="tag gloss zz",
        actor_user_id=None,
        actor_token_id=None,
    )
    entity_id, head_id = _serving_entity(tag_ids=[tag.id])
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash="b63a08c2c86b426233a6dd2e6f78199087e9580493ec0e2cec3a4c24fe38f590",
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None
    updated = update_tag(
        tag.id,
        name=None,
        name_set=False,
        description="revised gloss",
        description_set=True,
        actor_user_id=None,
        actor_token_id=None,
    )
    assert updated.description == "revised gloss"
    current = current_projection(entity_id)
    assert current is not None
    assert current.embedding == (1.0, 0.0)


def test_deprecating_a_serving_entity_drops_the_vector_without_a_model() -> None:
    from backend.entity.projection import current_projection, retain_projection

    entity_id, head_id = _serving_entity()
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=head_id,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None
    saved = deprecate_entity(
        entity_id=entity_id,
        actor_user_id=None,
        actor_token_id=None,
    )
    assert saved["deprecated_at"] is not None
    assert current_projection(entity_id) is None


def _publish_current(entity_id: str, monkeypatch: pytest.MonkeyPatch) -> str:
    from backend.entity.align import run_entity_table_job
    from backend.entity.publish import accept
    from backend.jobs.store import get_job_store
    from backend.worker.parameters import assemble_system_parameters

    assemble_system_parameters()

    def _inline(job: object) -> str:
        run_entity_table_job(getattr(job, "id"))
        return str(getattr(job, "id"))

    monkeypatch.setattr("backend.entity.jobs.dispatch_entity_job", _inline)
    current = get_entity_store().current_version(entity_id)
    assert current is not None
    job, created = accept(
        entity_id=entity_id,
        version_id=current.id,
        actor_user_id="usr_projection",
        actor_token_id=None,
    )
    assert created
    finished = get_job_store().get(job.id)
    assert finished is not None
    assert finished.status == "succeeded", finished.error_summary
    head = latest_published_of(get_entity_store().list_all_versions(entity_id))
    assert head is not None
    return head.id


def test_an_attribute_only_publish_drops_the_vector_when_the_text_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.entity.projection import canonical_text, current_projection, retain_projection

    saved = create_entity(
        table_name="materials",
        name="Material",
        description="A stock item",
        attributes=[_SKU],
        actor_user_id=None,
        actor_token_id=None,
    )
    entity_id = str(saved["id"])
    first_head = _publish_current(entity_id, monkeypatch)
    retained = retain_projection(
        entity_id=entity_id,
        head_version_id=first_head,
        content_hash=_SERVING_HASH,
        generation=5,
        processing_contract=_CONTRACT,
        embedding=(1.0, 0.0),
    )
    assert retained is not None
    open_version(
        entity_id=entity_id,
        attributes=[_SKU, AttributeRecord(name="note", type="text")],
        actor_user_id=None,
        actor_token_id=None,
    )
    assert canonical_text(entity_id) == "materials\nMaterial\nA stock item"
    assert current_projection(entity_id) is not None
    second_head = _publish_current(entity_id, monkeypatch)
    assert second_head != first_head
    assert canonical_text(entity_id) == "materials\nMaterial\nA stock item"
    assert current_projection(entity_id) is None


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_Body":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def test_embed_persists_the_vector_returned_by_the_shared_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.admin.model_services import openai_compat
    from backend.entity.projection import current_projection, embed_entity

    entity_id, head_id = _serving_entity()
    _seed_embedding(generation=4)
    captured: dict[str, object] = {}

    def _urlopen(req: object, timeout: int = 0) -> _Body:
        del timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))  # type: ignore[attr-defined]
        body = json.dumps({"data": [{"index": 0, "embedding": [0.5, 0.5]}]}).encode()
        return _Body(body)

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    saved = embed_entity(entity_id)
    assert captured["payload"] == {
        "model": "qwen-test",
        "input": ["materials\nMaterial\nA stock item"],
    }
    assert saved.entity_id == entity_id
    assert saved.head_version_id == head_id
    assert saved.content_hash == _SERVING_HASH
    assert saved.generation == 4
    assert saved.processing_contract == _CONTRACT
    assert saved.embedding == (0.5, 0.5)
    assert current_projection(entity_id) == saved
