"""Entity SQL Problem Codes."""

from __future__ import annotations

from backend.entity.errors import EntitySqlFailed, EntitySqlInvalid, EntitySqlTimeout


def test_entity_sql_invalid_is_a_bad_request() -> None:
    error = EntitySqlInvalid()
    assert error.code == "ENTITY_SQL_INVALID"
    assert error.http_status == 400
    assert error.message == "Entity SQL is invalid"
    named = EntitySqlInvalid("SELECT INTO is not allowed")
    assert named.code == "ENTITY_SQL_INVALID"
    assert named.message == "SELECT INTO is not allowed"


def test_entity_sql_timeout_is_gateway_timeout() -> None:
    error = EntitySqlTimeout()
    assert error.code == "ENTITY_SQL_TIMEOUT"
    assert error.http_status == 504
    assert error.message == "Entity SQL exceeded the platform timeout"


def test_entity_sql_failed_carries_sqlstate() -> None:
    error = EntitySqlFailed(sqlstate="42P01")
    assert error.code == "ENTITY_SQL_FAILED"
    assert error.http_status == 502
    assert error.extra_members() == {"sqlstate": "42P01"}
    assert "42P01" in error.message
    plain = EntitySqlFailed()
    assert plain.message == "Entity SQL execution failed"
    assert plain.extra_members() == {}
    rewritten = EntitySqlFailed("relation orders does not exist", sqlstate="42P01")
    assert rewritten.message == "relation orders does not exist"
    assert rewritten.extra_members() == {"sqlstate": "42P01"}
