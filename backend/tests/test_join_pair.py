"""Directed join-pair admission and insert-if-missing persist."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import pytest

from backend.metadata.catalog.join_changes import (
    JOIN_CHANGE_CREATE,
    CatalogJoinChangeRecord,
)
from backend.metadata.catalog.join_pair import (
    Inserted,
    Occupied,
    apply_insert_join,
    decide_pair_write,
    pair_state,
)
from backend.metadata.catalog.records import CatalogJoinRecord


def _join(
    *,
    join_id: str = "join_1",
    rejected: bool = False,
) -> CatalogJoinRecord:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return CatalogJoinRecord(
        id=join_id,
        from_column_id="col_a",
        to_column_id="col_b",
        evidence="evidence",
        join_kind="INNER",
        join_expression="a = b",
        created_by_user_id=None,
        created_at=now,
        rejected_at=now if rejected else None,
        rejected_by_user_id="user_1" if rejected else None,
    )


@pytest.mark.parametrize(
    ("existing", "expected"),
    [
        (None, "absent"),
        (_join(rejected=False), "asserted"),
        (_join(rejected=True), "rejected"),
    ],
)
def test_pair_state(
    existing: CatalogJoinRecord | None, expected: str
) -> None:
    assert pair_state(existing) == expected


@pytest.mark.parametrize(
    ("state", "writer", "expected_action"),
    [
        ("absent", "automatic", "insert"),
        ("absent", "human_single", "insert"),
        ("absent", "human_batch", "insert"),
        ("asserted", "automatic", "skip_protected"),
        ("asserted", "human_single", "refuse_defined"),
        ("asserted", "human_batch", "skip_protected"),
        ("rejected", "automatic", "skip_rejected"),
        ("rejected", "human_single", "refuse_rejected"),
        ("rejected", "human_batch", "skip_rejected"),
    ],
)
def test_decide_pair_write(
    state: Literal["absent", "asserted", "rejected"],
    writer: Literal["automatic", "human_single", "human_batch"],
    expected_action: str,
) -> None:
    existing_id = None if state == "absent" else "join_existing"
    decision = decide_pair_write(state, writer=writer, existing_id=existing_id)
    assert decision.action == expected_action
    if expected_action.startswith("refuse_"):
        assert decision.existing_id == "join_existing"
    else:
        assert decision.existing_id is None


@dataclass
class _FakePort:
    existing: CatalogJoinRecord | None = None
    insert_returns_none: bool = False
    joins: dict[tuple[str, str], CatalogJoinRecord] = field(default_factory=dict)
    changes: list[CatalogJoinChangeRecord] = field(default_factory=list)

    def get_join_by_pair(
        self, from_column_id: str, to_column_id: str
    ) -> CatalogJoinRecord | None:
        if self.existing is not None:
            return self.existing
        return self.joins.get((from_column_id, to_column_id))

    def insert_join(self, record: CatalogJoinRecord) -> CatalogJoinRecord | None:
        if self.insert_returns_none:
            return None
        pair = (record.from_column_id, record.to_column_id)
        self.joins[pair] = record
        return record

    def append_join_change(self, change: CatalogJoinChangeRecord) -> None:
        self.changes.append(change)


def test_apply_insert_join_absent_inserts_and_appends_create() -> None:
    port = _FakePort()
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    result = apply_insert_join(
        port,
        from_column_id="col_a",
        to_column_id="col_b",
        evidence="fk",
        created_by_user_id="user_1",
        join_kind="INNER",
        join_expression="a = b",
        attester="human",
        now=now,
    )
    assert isinstance(result, Inserted)
    assert result.record.from_column_id == "col_a"
    assert result.record.created_by_user_id == "user_1"
    assert len(port.changes) == 1
    assert port.changes[0].kind == JOIN_CHANGE_CREATE
    assert port.changes[0].attester == "human"
    assert port.changes[0].actor_user_id == "user_1"


def test_apply_insert_join_existing_occupied_no_change() -> None:
    existing = _join(join_id="join_planted")
    port = _FakePort(existing=existing)
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    result = apply_insert_join(
        port,
        from_column_id="col_a",
        to_column_id="col_b",
        evidence="new",
        created_by_user_id="user_1",
        join_kind="INNER",
        join_expression="a = b",
        attester="human",
        now=now,
    )
    assert isinstance(result, Occupied)
    assert result.record.id == "join_planted"
    assert port.changes == []


def test_apply_insert_join_race_occupied_no_change_no_restate() -> None:
    raced = _join(join_id="join_raced")
    lookups = {"n": 0}

    @dataclass
    class _RacePort:
        changes: list[CatalogJoinChangeRecord] = field(default_factory=list)

        def get_join_by_pair(
            self, from_column_id: str, to_column_id: str
        ) -> CatalogJoinRecord | None:
            lookups["n"] += 1
            if lookups["n"] == 1:
                return None
            return raced

        def insert_join(self, record: CatalogJoinRecord) -> CatalogJoinRecord | None:
            return None

        def append_join_change(self, change: CatalogJoinChangeRecord) -> None:
            self.changes.append(change)

    port = _RacePort()
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    result = apply_insert_join(
        port,
        from_column_id="col_a",
        to_column_id="col_b",
        evidence="race",
        created_by_user_id=None,
        join_kind="INNER",
        join_expression="a = b",
        attester="sql_lineage",
        now=now,
    )
    assert isinstance(result, Occupied)
    assert result.record.id == "join_raced"
    assert port.changes == []
    assert lookups["n"] == 2


def _seed_pair_for_delete() -> tuple[str, str]:
    from backend.core.time import utc_now
    from backend.metadata.catalog.records import (
        CatalogColumnRecord,
        CatalogObjectRecord,
    )
    from backend.metadata.catalog.structure_refresh import apply_structure_snapshot
    from backend.metadata.sources.service import require_source
    from backend.metadata.sources.store import SourceRecord, get_source_store

    now = utc_now()
    get_source_store().create_source(
        SourceRecord(
            id="src_del",
            key="del-demo",
            locator_key="src/postgresql/del-demo",
            name="Del",
            kind="database",
            status="active",
            description=None,
            engine="postgresql",
            access_ciphertext=None,
            access_updated_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    cols = [
        CatalogColumnRecord(
            id="col_del_a",
            object_id="obj_del",
            locator_key="col/obj_del/a",
            name="a",
            ordinal=0,
            data_type="integer",
            nullable=False,
            is_present=True,
            default_value=None,
            comment=None,
            business_name=None,
            business_description=None,
            column_semantics=None,
            enum_catalog=None,
            semantic_source=None,
            field_kind="column",
            created_at=now,
            updated_at=now,
        ),
        CatalogColumnRecord(
            id="col_del_b",
            object_id="obj_del",
            locator_key="col/obj_del/b",
            name="b",
            ordinal=1,
            data_type="integer",
            nullable=False,
            is_present=True,
            default_value=None,
            comment=None,
            business_name=None,
            business_description=None,
            column_semantics=None,
            enum_catalog=None,
            semantic_source=None,
            field_kind="column",
            created_at=now,
            updated_at=now,
        ),
    ]
    apply_structure_snapshot(
        source=require_source("src_del"),
        job_id="job_seed",
        collected=[
            CatalogObjectRecord(
                id="obj_del",
                source_id="src_del",
                locator_key="obj/postgresql/del-demo/public/table/T",
                object_type="table",
                schema_name="public",
                name="T",
                ddl=None,
                comment=None,
                primary_key=["a"],
                is_present=True,
                business_name=None,
                business_description=None,
                object_category=None,
                grain_description=None,
                business_primary_key=None,
                business_domain_id=None,
                evidence_summary=None,
                open_questions=None,
                semantic_source=None,
                business_semantics_ready=False,
                semantics_updated_at=None,
                last_structure_job_id="job_seed",
                collected_at=now,
                created_at=now,
                updated_at=now,
                columns=cols,
                foreign_keys=[],
                indexes=[],
            )
        ],
        schema_scope=None,
        fail_safe_threshold=1.0,
    )
    return "col_del_a", "col_del_b"


def test_delete_join_refuses_automatic() -> None:
    from backend.admin.audit_store import get_audit_store
    from backend.metadata.catalog import join_writes as catalog_joins
    from backend.metadata.catalog.join_origin import SQL_LINEAGE_JOIN_ORIGIN
    from backend.metadata.catalog.store import get_catalog_store
    from backend.metadata.errors import JoinDeleteAutomatic

    a, b = _seed_pair_for_delete()
    auto = get_catalog_store().write_insert_join(
        from_column_id=a,
        to_column_id=b,
        evidence="SQL join",
        created_by_user_id=None,
        attester=SQL_LINEAGE_JOIN_ORIGIN,
    ).record
    with pytest.raises(JoinDeleteAutomatic) as exc:
        catalog_joins.delete_join(
            join_id=auto.id,
            actor_user_id="user_1",
            actor_token_id=None,
        )
    assert exc.value.join_id == auto.id
    assert get_catalog_store().get_join(auto.id) is not None
    events, _ = get_audit_store().list_events(action="join.delete")
    assert events == []


def test_delete_join_refuses_rejected_manual() -> None:
    from backend.core.time import utc_now
    from backend.metadata.catalog import join_writes as catalog_joins
    from backend.metadata.catalog.join_origin import HUMAN_JOIN_ORIGIN
    from backend.metadata.catalog.store import get_catalog_store
    from backend.metadata.errors import JoinRejected

    a, b = _seed_pair_for_delete()
    store = get_catalog_store()
    human = store.write_insert_join(
        from_column_id=a,
        to_column_id=b,
        evidence="manual",
        created_by_user_id="user_1",
        attester=HUMAN_JOIN_ORIGIN,
    ).record
    rejected = store.set_join_rejection(
        human.id,
        rejected_at=utc_now(),
        rejected_by_user_id="user_1",
        actor_user_id="user_1",
    )
    assert rejected is not None
    with pytest.raises(JoinRejected) as exc:
        catalog_joins.delete_join(
            join_id=human.id,
            actor_user_id="user_1",
            actor_token_id=None,
        )
    assert exc.value.join_id == human.id
    assert store.get_join(human.id) is not None


def test_delete_join_refuses_rejected_automatic_as_automatic() -> None:
    from backend.core.time import utc_now
    from backend.metadata.catalog import join_writes as catalog_joins
    from backend.metadata.catalog.join_origin import SQL_LINEAGE_JOIN_ORIGIN
    from backend.metadata.catalog.store import get_catalog_store
    from backend.metadata.errors import JoinDeleteAutomatic

    a, b = _seed_pair_for_delete()
    store = get_catalog_store()
    auto = store.write_insert_join(
        from_column_id=a,
        to_column_id=b,
        evidence="SQL join",
        created_by_user_id=None,
        attester=SQL_LINEAGE_JOIN_ORIGIN,
    ).record
    store.set_join_rejection(
        auto.id,
        rejected_at=utc_now(),
        rejected_by_user_id="user_1",
        actor_user_id="user_1",
    )
    with pytest.raises(JoinDeleteAutomatic) as exc:
        catalog_joins.delete_join(
            join_id=auto.id,
            actor_user_id="user_1",
            actor_token_id=None,
        )
    assert exc.value.join_id == auto.id


def test_delete_join_allows_manual_asserted_and_audits() -> None:
    from backend.admin.audit_store import get_audit_store
    from backend.metadata.catalog import join_writes as catalog_joins
    from backend.metadata.catalog.join_origin import HUMAN_JOIN_ORIGIN
    from backend.metadata.catalog.store import get_catalog_store

    a, b = _seed_pair_for_delete()
    human = get_catalog_store().write_insert_join(
        from_column_id=a,
        to_column_id=b,
        evidence="manual",
        created_by_user_id="user_1",
        attester=HUMAN_JOIN_ORIGIN,
    ).record
    catalog_joins.delete_join(
        join_id=human.id,
        actor_user_id="user_1",
        actor_token_id=None,
    )
    assert get_catalog_store().get_join(human.id) is None
    events, _ = get_audit_store().list_events(action="join.delete")
    assert len(events) == 1
    assert events[0].resource_id == human.id


