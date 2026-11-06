"""ADR 0054 checks missing from the bootstrap and profile-view suites.

Observable behaviour on a throwaway PostgreSQL 18 entity database: operator
leakproof flags, initPlan evaluation of ``acl.*`` helpers, pooled ``SET LOCAL``,
and what the reader role can read in the catalogs. Does not start Docker.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

from backend.entity.access.context import sign_payload
from backend.entity.ddl import table_security_statements
from backend.tests.entity_pg import EntityDatabase, bootstrapped_entity_database
from backend.tests.test_entity_bootstrap_pg import _leakproof_operators

pytestmark = pytest.mark.integration

_MAINTENANCE_DATABASE_URL = os.getenv(
    "REFRAQ_INTEGRATION_MAINTENANCE_DATABASE_URL",
    "postgresql+psycopg://refraq:refraq@127.0.0.1:5432/refraq",
)
# CVE-2026-14666 is fixed in PostgreSQL 18.6.
_CVE_2026_14666_FIXED_IN = 180006
_COMPARISONS = ("=", "<>", "<", "<=", ">", ">=")
# Attribute types filter_is_leakproof treats as leakproof comparisons, and the
# PostgreSQL types those comparisons use. string / text / dictionary / user are
# varchar or text; varchar has no same-type operator and resolves to text.
_RELIED_TYPES = ("text", "int8", "float8", "bool", "date", "timestamptz", "time")
_RELIED_OPERATORS = ("=", "<", "<=", ">", ">=")
_LEAKPROOF_TYPES = ("bool", "date", "float8", "int8", "text", "time", "timestamptz")
_NOT_LEAKPROOF_TYPES = ("jsonb", "numeric")
_SECRET = b"k" * 32


def _postgres_available() -> bool:
    engine = create_engine(_MAINTENANCE_DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


def _engine(url: str, **kwargs: object) -> Engine:
    return create_engine(url, **kwargs)


@pytest.fixture(scope="module")
def entity() -> Iterator[EntityDatabase]:
    if not _postgres_available():
        pytest.skip("Postgres not available")
    with bootstrapped_entity_database(_MAINTENANCE_DATABASE_URL, "refraq_adr54") as urls:
        admin = _engine(urls.admin_url)
        try:
            with admin.begin() as conn:
                conn.execute(
                    text("SELECT acl.install_key(:kid, :secret)"),
                    {"kid": "k1", "secret": _SECRET},
                )
        finally:
            admin.dispose()
        yield urls


def _token(secret: bytes, **overrides: object) -> str:
    payload: dict[str, object] = {
        "sub": "user_1",
        "grants": ["g1"],
        "attrs": {"dept": "eng"},
        "rev": {"ent_adr": 1},
        "exp": int(time.time()) + 3600,
        "req": "req_adr",
        "kid": "k1",
    }
    payload.update(overrides)
    return sign_payload(payload, secret)


def _tamper(token: str) -> str:
    """Rewrite the payload and keep the original signature."""
    body, signature = token.split(".", 1)
    payload = json.loads(base64.b64decode(body))
    payload["grants"] = ["g2"]
    payload["sub"] = "user_2"
    rewritten = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return rewritten + "." + signature


def _expected_leakproof() -> dict[tuple[str, str], bool]:
    table = {
        (typ, op): True for typ in _LEAKPROOF_TYPES for op in _COMPARISONS
    }
    table.update(
        {(typ, op): False for typ in _NOT_LEAKPROOF_TYPES for op in _COMPARISONS}
    )
    table[("text", "~~")] = False
    table[("text", "~~*")] = False
    return table


def _plan_nodes(plan: object) -> list[dict[str, object]]:
    document = json.loads(plan) if isinstance(plan, str) else plan
    if isinstance(document, list):
        root = document[0]["Plan"]
    elif isinstance(document, dict):
        root = document["Plan"]
    else:
        raise AssertionError(plan)
    nodes: list[dict[str, object]] = []

    def walk(node: dict[str, object]) -> None:
        nodes.append(node)
        for child in node.get("Plans") or []:
            if isinstance(child, dict):
                walk(child)

    assert isinstance(root, dict)
    walk(root)
    return nodes


def _is_initplan(node: dict[str, object]) -> bool:
    if node.get("Parent Relationship") == "InitPlan":
        return True
    return str(node.get("Subplan Name") or "").startswith("InitPlan")


def _node_text(node: dict[str, object]) -> str:
    return " ".join(
        json.dumps(node.get(key))
        for key in (
            "Output",
            "Filter",
            "Index Cond",
            "Recheck Cond",
            "One-Time Filter",
            "Subplan Name",
        )
    )


def test_postgresql_minor_includes_cve_2026_14666() -> None:
    if not _postgres_available():
        pytest.skip("Postgres not available")
    engine = _engine(_MAINTENANCE_DATABASE_URL)
    try:
        with engine.connect() as conn:
            number = int(conn.execute(text("SHOW server_version_num")).scalar_one())
            version = str(conn.execute(text("SHOW server_version")).scalar_one())
    finally:
        engine.dispose()
    assert number >= _CVE_2026_14666_FIXED_IN, (version, number)


def test_leakproof_operators_match_profile_filter_path(entity: EntityDatabase) -> None:
    catalog = _leakproof_operators(entity.admin_url)
    expected = _expected_leakproof()
    assert catalog == expected, catalog
    missing = [key for key in catalog if key[0] == "varchar"]
    assert missing == []
    for typ in _RELIED_TYPES:
        for op in _RELIED_OPERATORS:
            assert catalog[(typ, op)] is True, (typ, op)


def test_acl_helpers_initplan_once_and_barrier_holds(entity: EntityDatabase) -> None:
    admin = _engine(entity.admin_url)
    reader = _engine(entity.reader_url)
    try:
        with admin.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE entity_data.adr_init ("
                    "row_id bigint PRIMARY KEY, open_row boolean NOT NULL, secret text)"
                )
            )
            for statement in table_security_statements("entity_data", "adr_init"):
                conn.exec_driver_sql(statement)
            conn.execute(
                text(
                    "INSERT INTO entity_data.adr_init (row_id, open_row, secret) "
                    "VALUES (:id, :open_row, :secret)"
                ),
                [
                    {
                        "id": row_id,
                        "open_row": row_id > 2,
                        "secret": "kept" if row_id > 2 else "boom",
                    }
                    for row_id in range(1, 9)
                ],
            )
            conn.execute(
                text(
                    "CREATE VIEW entity_access.adr_init "
                    "WITH (security_barrier = true, security_invoker = false) AS "
                    "SELECT s.row_id, "
                    "CASE WHEN s.g1 THEN s.secret ELSE NULL END AS shown "
                    "FROM ("
                    "  SELECT t.row_id, t.secret, COALESCE("
                    "    (SELECT acl.grant_active('g1'))"
                    "    AND (SELECT acl.rev_ok('ent_adr', 1))"
                    "    AND (SELECT acl.subject_text('dept')) = 'eng'"
                    "    AND t.open_row, false) AS g1 "
                    "  FROM entity_data.adr_init t"
                    ") s WHERE s.g1"
                )
            )
            conn.execute(
                text('ALTER VIEW entity_access.adr_init OWNER TO "refraq_exposure_owner"')
            )
            conn.execute(
                text('GRANT SELECT ON entity_access.adr_init TO "refraq_reader"')
            )
            conn.execute(text("CREATE SCHEMA adr_probe"))
            conn.execute(text('GRANT USAGE ON SCHEMA adr_probe TO "refraq_reader"'))
            conn.execute(
                text(
                    "CREATE FUNCTION adr_probe.adr_leak(v text) RETURNS boolean "
                    "LANGUAGE plpgsql AS $fn$ "
                    "BEGIN "
                    "  IF v = 'boom' THEN RAISE EXCEPTION 'leaked'; END IF; "
                    "  RETURN true; "
                    "END $fn$"
                )
            )
            conn.execute(
                text('GRANT EXECUTE ON FUNCTION adr_probe.adr_leak(text) TO "refraq_reader"')
            )
        good = _token(_SECRET)
        with reader.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.ctx', :token, true)"), {"token": good}
            )
            shown = conn.execute(
                text("SELECT shown FROM entity_access.adr_init ORDER BY row_id")
            ).scalars().all()
            assert shown == ["kept"] * 6
            plan = conn.execute(
                text(
                    "EXPLAIN (ANALYZE, VERBOSE, FORMAT JSON) "
                    "SELECT shown FROM entity_access.adr_init"
                )
            ).scalar_one()
            nodes = _plan_nodes(plan)
            initplans = [node for node in nodes if _is_initplan(node)]
            assert initplans, plan
            for node in initplans:
                assert int(node["Actual Loops"]) == 1, plan
            owned = [_node_text(node) for node in nodes]
            blob = "\n".join(owned)
            for name in ("grant_active", "rev_ok", "subject_text"):
                assert name in blob, plan
            for node, text_blob in zip(nodes, owned, strict=True):
                if not any(name in text_blob for name in ("grant_active", "rev_ok", "subject_text")):
                    continue
                loops = node.get("Actual Loops")
                if loops is not None:
                    assert int(loops) == 1, plan
            leaked = conn.execute(
                text(
                    "EXPLAIN (ANALYZE, FORMAT JSON) "
                    "SELECT shown FROM entity_access.adr_init "
                    "WHERE adr_probe.adr_leak(shown)"
                )
            ).scalar_one()
            _assert_leak_above_barrier(leaked, "adr_init")
            seen = conn.execute(
                text(
                    "SELECT shown FROM entity_access.adr_init "
                    "WHERE adr_probe.adr_leak(shown) ORDER BY row_id"
                )
            ).scalars().all()
            assert seen == ["kept"] * 6
            conn.execute(
                text("SELECT set_config('app.ctx', :token, true)"),
                {"token": _tamper(good)},
            )
            assert (
                conn.execute(text("SELECT count(*) FROM entity_access.adr_init")).scalar_one()
                == 0
            )
            conn.execute(
                text("SELECT set_config('app.ctx', :token, true)"), {"token": good}
            )
            assert (
                conn.execute(text("SELECT count(*) FROM entity_access.adr_init")).scalar_one()
                == 6
            )
    finally:
        reader.dispose()
        admin.dispose()


def _assert_leak_above_barrier(plan: object, relation: str) -> None:
    nodes = _plan_nodes(plan)
    scans = [node for node in nodes if node.get("Relation Name") == relation]
    assert scans, plan
    for scan in scans:
        blob = json.dumps(
            {
                key: scan.get(key)
                for key in ("Filter", "Index Cond", "Recheck Cond", "One-Time Filter")
            }
        )
        assert "adr_leak" not in blob, plan
    assert any("adr_leak" in json.dumps(node.get("Filter")) for node in nodes), plan


def test_set_local_context_clears_on_pooled_reuse(entity: EntityDatabase) -> None:
    good = _token(_SECRET)
    other = _token(_SECRET, grants=["g2"], req="req_other")
    reader = _engine(
        entity.reader_url,
        pool_size=1,
        max_overflow=0,
        pool_reset_on_return="rollback",
    )
    try:
        with reader.begin() as conn:
            pid = int(conn.execute(text("SELECT pg_backend_pid()")).scalar_one())
            conn.execute(
                text("SELECT set_config('app.ctx', :token, true)"), {"token": good}
            )
            assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is True
        with reader.begin() as conn:
            assert int(conn.execute(text("SELECT pg_backend_pid()")).scalar_one()) == pid
            setting = conn.execute(
                text("SELECT current_setting('app.ctx', true)")
            ).scalar_one()
            assert setting in (None, "")
            assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is False
            conn.execute(
                text("SELECT set_config('app.ctx', :token, true)"), {"token": good}
            )
            conn.execute(text("RESET app.ctx"))
            assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is False
            assert conn.execute(text("SELECT acl.subject_text('dept')")).scalar_one() is None
            conn.execute(
                text("SELECT set_config('app.ctx', :token, true)"),
                {"token": _tamper(good)},
            )
            assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is False
            assert conn.execute(text("SELECT acl.grant_active('g2')")).scalar_one() is False
            assert conn.execute(text("SELECT acl.subject_text('dept')")).scalar_one() is None
            conn.execute(
                text("SELECT set_config('app.ctx', :token, true)"), {"token": other}
            )
            assert conn.execute(text("SELECT acl.grant_active('g2')")).scalar_one() is True
            assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is False
        with reader.connect() as conn:
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(
                    text("SELECT acl.install_key('k9', :secret)"),
                    {"secret": b"z" * 32},
                )
            conn.rollback()
        with reader.begin() as conn:
            assert int(conn.execute(text("SELECT pg_backend_pid()")).scalar_one()) == pid
            assert conn.execute(text("SELECT acl.grant_active('g2')")).scalar_one() is False
            # is_local false is session-scoped: the reused backend keeps this
            # context until RESET. Callers must pass true (SET LOCAL).
            conn.execute(
                text("SELECT set_config('app.ctx', :token, false)"), {"token": good}
            )
            assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is True
        with reader.begin() as conn:
            assert int(conn.execute(text("SELECT pg_backend_pid()")).scalar_one()) == pid
            assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is True
            conn.execute(text("RESET app.ctx"))
            assert conn.execute(text("SELECT acl.grant_active('g1')")).scalar_one() is False
    finally:
        reader.dispose()


def test_reader_catalog_hides_key_material(entity: EntityDatabase) -> None:
    admin = _engine(entity.admin_url)
    reader = _engine(entity.reader_url)
    secret_hex = _SECRET.hex()
    try:
        with admin.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE entity_data.adr_cat ("
                    "row_id bigint PRIMARY KEY, secret text, public_name text)"
                )
            )
            for statement in table_security_statements("entity_data", "adr_cat"):
                conn.exec_driver_sql(statement)
            conn.execute(
                text(
                    "INSERT INTO entity_data.adr_cat (row_id, secret, public_name) "
                    "VALUES (1, 'ROWVALUE9f3a', 'ada')"
                )
            )
            conn.execute(
                text(
                    "CREATE VIEW entity_access.adr_cat "
                    "WITH (security_barrier = true, security_invoker = false) AS "
                    "SELECT row_id, public_name, "
                    "CASE WHEN (SELECT acl.grant_active('g_cat')) THEN secret ELSE NULL END "
                    "AS shown "
                    "FROM entity_data.adr_cat "
                    "WHERE (SELECT acl.rev_ok('ent_cat', 4))"
                )
            )
            conn.execute(
                text('ALTER VIEW entity_access.adr_cat OWNER TO "refraq_exposure_owner"')
            )
            conn.execute(text('GRANT SELECT ON entity_access.adr_cat TO "refraq_reader"'))
            conn.execute(
                text(
                    "CREATE VIEW entity_access.adr_cat_sealed "
                    "WITH (security_barrier = true, security_invoker = false) AS "
                    "SELECT row_id, secret AS sealed_col FROM entity_data.adr_cat"
                )
            )
            conn.execute(
                text(
                    "ALTER VIEW entity_access.adr_cat_sealed "
                    "OWNER TO \"refraq_exposure_owner\""
                )
            )
        with reader.connect() as conn:
            relations = {
                (schema, name)
                for schema, name in conn.execute(
                    text(
                        "SELECT n.nspname, c.relname "
                        "FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname IN ('entity_data', 'entity_access', 'acl') "
                        "AND c.relkind IN ('r', 'v', 'p')"
                    )
                )
            }
            assert ("entity_data", "adr_cat") in relations
            assert ("entity_access", "adr_cat") in relations
            assert ("entity_access", "adr_cat_sealed") in relations
            assert ("acl", "signing_keys") in relations
            assert ("acl", "mask_key") in relations
            columns = {
                (schema, relation, column)
                for schema, relation, column in conn.execute(
                    text(
                        "SELECT n.nspname, c.relname, a.attname "
                        "FROM pg_attribute a "
                        "JOIN pg_class c ON c.oid = a.attrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname IN ('entity_data', 'entity_access', 'acl') "
                        "AND a.attnum > 0 AND NOT a.attisdropped"
                    )
                )
            }
            assert ("entity_data", "adr_cat", "secret") in columns
            assert ("entity_access", "adr_cat", "shown") in columns
            assert ("entity_access", "adr_cat_sealed", "sealed_col") in columns
            assert ("acl", "signing_keys", "secret") in columns
            granted = conn.execute(
                text(
                    "SELECT definition FROM pg_views "
                    "WHERE schemaname = 'entity_access' AND viewname = 'adr_cat'"
                )
            ).scalar_one()
            sealed = conn.execute(
                text(
                    "SELECT pg_get_viewdef(c.oid) "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'entity_access' AND c.relname = 'adr_cat_sealed'"
                )
            ).scalar_one()
            info = conn.execute(
                text(
                    "SELECT view_definition FROM information_schema.views "
                    "WHERE table_schema = 'entity_access' AND table_name = 'adr_cat'"
                )
            ).scalar_one()
            assert info is None
            assert granted and "grant_active" in granted and "ent_cat" in granted
            assert "ROWVALUE9f3a" not in granted
            assert secret_hex not in granted
            assert sealed and "sealed_col" in sealed
            assert "ROWVALUE9f3a" not in sealed
            bodies = conn.execute(
                text(
                    "SELECT p.proname, p.prosrc "
                    "FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'acl'"
                )
            ).all()
            by_name = {str(name): source or "" for name, source in bodies}
            assert "signing_keys" in by_name["ctx_payload"]
            assert "grant_active" in by_name["grant_active"] or "grants" in by_name["grant_active"]
            for source in by_name.values():
                assert secret_hex not in source
                assert "ROWVALUE9f3a" not in source
            private_routines = conn.execute(
                text(
                    "SELECT routine_definition FROM information_schema.routines "
                    "WHERE specific_schema = 'acl' AND routine_name = 'ctx_payload'"
                )
            ).all()
            granted_routine = conn.execute(
                text(
                    "SELECT routine_definition FROM information_schema.routines "
                    "WHERE specific_schema = 'acl' AND routine_name = 'grant_active'"
                )
            ).scalar_one()
            assert private_routines == []
            assert granted_routine is None
            function_def = conn.execute(
                text(
                    "SELECT pg_get_functiondef(p.oid) "
                    "FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = 'acl' AND p.proname = 'ctx_payload'"
                )
            ).scalar_one()
            assert function_def and "signing_keys" in function_def
            assert secret_hex not in function_def
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text("SELECT encode(secret, 'hex') FROM acl.signing_keys"))
            conn.rollback()
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text("SELECT encode(secret, 'hex') FROM acl.mask_key"))
            conn.rollback()
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text("SELECT acl.ctx_payload()"))
            conn.rollback()
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text("SELECT secret FROM entity_data.adr_cat"))
            conn.rollback()
            with pytest.raises(ProgrammingError, match="permission denied"):
                conn.execute(text("SELECT sealed_col FROM entity_access.adr_cat_sealed"))
            conn.rollback()
    finally:
        reader.dispose()
        admin.dispose()
