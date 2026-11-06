"""SQL verb records on the Entity Access Log (memory store)."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.entity.access.actor_token import actor_token
from backend.entity.access.records import AccessLogRecord
from backend.entity.access.store import get_access_store
from backend.entity.ids import new_access_log_id


def test_sql_append_stores_hash_summary_and_shared_request() -> None:
    from backend.entity.access.enforce import append_sql_log

    summary = ("S" * 200) + "TAIL"
    grants = ["g1", "g2"]
    with actor_token("pat_from_carrier"):
        append_sql_log(
            user_id="user_1",
            request_id="req_shared",
            pat_id="pat_argument",
            entity_id="ent_orders",
            effective_grant_ids=grants,
            view_name="v_orders",
            policy_revision=3,
            row_count=7,
            outcome_code="ok",
            duration_ms=42,
            sql_sha256="ab" * 32,
            statement_summary=summary,
        )
    grants.append("g3")
    append_sql_log(
        user_id="user_1",
        request_id="req_shared",
        pat_id=None,
        entity_id="ent_customers",
        effective_grant_ids=["g9"],
        view_name=None,
        policy_revision=1,
        row_count=None,
        outcome_code="ENTITY_SQL_FAILED",
        duration_ms=5,
        sql_sha256="cd" * 32,
        statement_summary="select 1",
    )
    get_access_store().append_log(
        AccessLogRecord(
            id=new_access_log_id(),
            created_at=datetime.now(timezone.utc),
            user_id="user_1",
            pat_id=None,
            request_id="req_other",
            entity_id="ent_orders",
            verb="get",
            effective_grant_ids=[],
            narrowing=None,
            view_name=None,
            policy_revision=3,
            row_count=1,
            outcome_code="ok",
            preview_subject_user_id=None,
            duration_ms=1,
        )
    )

    orders = get_access_store().logs_for_entity("ent_orders")
    assert [item.verb for item in orders] == ["sql", "get"]
    sql_log = orders[0]
    assert sql_log.user_id == "user_1"
    assert sql_log.pat_id == "pat_argument"
    assert sql_log.request_id == "req_shared"
    assert sql_log.effective_grant_ids == ["g1", "g2"]
    assert sql_log.view_name == "v_orders"
    assert sql_log.policy_revision == 3
    assert sql_log.row_count == 7
    assert sql_log.outcome_code == "ok"
    assert sql_log.duration_ms == 42
    assert sql_log.sql_sha256 == "ab" * 32
    assert sql_log.statement_summary == "S" * 200
    assert len(sql_log.statement_summary) == 200
    assert sql_log.narrowing is None
    assert sql_log.preview_subject_user_id is None
    assert orders[1].sql_sha256 is None
    assert orders[1].statement_summary is None

    customers = get_access_store().logs_for_entity("ent_customers")
    assert len(customers) == 1
    assert customers[0].verb == "sql"
    assert customers[0].request_id == "req_shared"
    assert customers[0].pat_id is None
    assert customers[0].sql_sha256 == "cd" * 32
    assert customers[0].statement_summary == "select 1"
    assert customers[0].outcome_code == "ENTITY_SQL_FAILED"
    assert customers[0].view_name is None
    assert customers[0].row_count is None
