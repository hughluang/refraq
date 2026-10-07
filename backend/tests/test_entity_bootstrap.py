"""SQL the entity bootstrap emits. No database connection."""

from __future__ import annotations

import pytest

from backend.entity.bootstrap import (
    BootstrapPlanError,
    LegacyRelation,
    acl_statements,
    move_statements,
    role_statements,
    schema_statements,
    secure_existing_table_statements,
)
from backend.entity.ddl import (
    ACL_OWNER_ROLE,
    ENTITY_OWNER_ROLE,
    READER_ROLE,
)


def test_role_statements_create_then_alter_and_quote_passwords() -> None:
    created = role_statements(
        owner_password="o'brien",
        reader_password="r",
        existing=frozenset(),
    )
    assert created[0].startswith(f'CREATE ROLE "{ENTITY_OWNER_ROLE}"')
    assert "PASSWORD 'o''brien'" in created[0]
    assert "LOGIN" in created[0]
    assert "NOSUPERUSER" in created[0]
    assert "NOBYPASSRLS" in created[0]
    assert "NOINHERIT" in created[0]
    reader = next(stmt for stmt in created if stmt.startswith(f'CREATE ROLE "{READER_ROLE}"'))
    assert "LOGIN" in reader
    altered = role_statements(
        owner_password="x",
        reader_password="y",
        existing=frozenset({ENTITY_OWNER_ROLE, READER_ROLE}),
    )
    assert altered[0].startswith(f'ALTER ROLE "{ENTITY_OWNER_ROLE}"')
    assert any("default_transaction_read_only = on" in stmt for stmt in altered)
    assert any("statement_timeout" in stmt for stmt in altered)
    with pytest.raises(BootstrapPlanError):
        role_statements(owner_password="a\x00b", reader_password="y", existing=frozenset())


def test_schema_statements_hide_entity_data_from_the_reader() -> None:
    sql = "\n".join(schema_statements())
    assert "CREATE SCHEMA IF NOT EXISTS \"entity_data\"" in sql
    assert "CREATE SCHEMA IF NOT EXISTS \"entity_access\"" in sql
    assert "CREATE SCHEMA IF NOT EXISTS \"acl\"" in sql
    assert f'REVOKE ALL ON SCHEMA "entity_data" FROM "{READER_ROLE}"' in sql
    assert f'GRANT USAGE ON SCHEMA "entity_access" TO "{READER_ROLE}"' in sql
    assert 'CREATE ON SCHEMA "entity_data"' not in sql


def test_acl_statements_are_definer_stable_and_fail_closed() -> None:
    sql = acl_statements(pgcrypto_schema=None)
    text = "\n".join(sql)
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA \"acl\"" in text
    assert "slot IN (1, 2)" in text
    assert "SECURITY DEFINER STABLE" in text
    assert "search_path = pg_catalog, pg_temp" in text
    for name in (
        "acl.grant_active(text)",
        "acl.rev_ok(text, integer)",
        "acl.subject_text(text)",
        "acl.subject_text_array(text)",
        "acl.mask_partial(text, integer, integer)",
        "acl.mask_email(text)",
        "acl.mask_hash(text)",
        "acl.mask_redact(text)",
    ):
        assert f"GRANT EXECUTE ON FUNCTION {name}" in text
        assert READER_ROLE in next(
            stmt for stmt in sql if stmt.startswith(f"GRANT EXECUTE ON FUNCTION {name}")
        )
    assert not any(
        stmt.startswith("GRANT EXECUTE ON FUNCTION acl.ctx_payload()") for stmt in sql
    )
    assert f'OWNER TO "{ACL_OWNER_ROLE}"' in text
    moved = "\n".join(acl_statements(pgcrypto_schema="public"))
    assert "ALTER EXTENSION pgcrypto SET SCHEMA \"acl\"" in moved
    assert "CREATE EXTENSION" not in moved


def test_move_and_secure_statements() -> None:
    assert move_statements("entity_data", [LegacyRelation("t", "r")], occupied=frozenset()) == []
    with pytest.raises(BootstrapPlanError, match="already holds"):
        move_statements(
            "public",
            [LegacyRelation("widget__v1__0123456789abcdef", "r")],
            occupied=frozenset({"widget__v1__0123456789abcdef"}),
        )
    moved = move_statements(
        "public",
        [
            LegacyRelation("stem", "v"),
            LegacyRelation("stem__v1__0123456789abcdef", "r"),
        ],
        occupied=frozenset(),
    )
    assert moved[0].startswith("ALTER TABLE")
    assert moved[1].startswith("ALTER VIEW")
    secured = "\n".join(
        secure_existing_table_statements(["stem__v1__0123456789abcdef"], ["stem"])
    )
    assert "ENABLE ROW LEVEL SECURITY" in secured
    assert "FORCE ROW LEVEL SECURITY" in secured
    assert 'TO "refraq_exposure_owner" USING (true)' in secured
    assert 'FOR ALL TO "refraq_entity_owner"' in secured
    assert 'OWNER TO "refraq_entity_owner"' in secured
