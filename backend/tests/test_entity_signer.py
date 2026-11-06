"""Signer login role: SQL grants, Entity MCP startup, and context signing."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.core.config import require_entity_reader_database_url
from backend.core.runtime import reset_runtime_capacity, set_process_role
from backend.entity.access.compiler import Policy, compile_policy
from backend.entity.access.enforce import read_context, reset_signing_ring
from backend.entity.access.facts import AttrFact, GrantSpec, Person, ProfileSpec
from backend.entity.bootstrap import (
    acl_statements,
    database_statements,
    role_statements,
    schema_statements,
)
from backend.entity.ddl import ENTITY_OWNER_ROLE, READER_ROLE, ident
from backend.entity.entity_db import (
    get_entity_signer_engine,
    open_entity_reader_pool_when_persistent,
)

SIGNER_ROLE = "refraq_signer"
_OWNER = "postgresql+psycopg://refraq_entity_owner:pw@127.0.0.1:5432/refraq_entity"
_READER = "postgresql+psycopg://refraq_reader:pw@127.0.0.1:5432/refraq_entity"
_SIGNER = "postgresql+psycopg://refraq_signer:pw@127.0.0.1:5432/refraq_entity"
_METADATA = "postgresql+psycopg://refraq:pw@127.0.0.1:5432/refraq"
_OTHER = "postgresql+psycopg://refraq_signer:pw@127.0.0.1:5432/other_entity"


def test_signer_role_logs_in_and_receives_only_the_signing_key_function() -> None:
    created = role_statements(
        owner_password="o",
        reader_password="r",
        signer_password="s'ecret",
        existing=frozenset(),
    )
    signer = next(stmt for stmt in created if f'CREATE ROLE "{SIGNER_ROLE}"' in stmt)
    assert "LOGIN" in signer
    assert "NOSUPERUSER" in signer
    assert "NOBYPASSRLS" in signer
    assert "NOINHERIT" in signer
    assert "PASSWORD 's''ecret'" in signer
    assert not any(
        SIGNER_ROLE in stmt and "default_transaction_read_only" in stmt for stmt in created
    )
    assert not any(SIGNER_ROLE in stmt and "statement_timeout" in stmt for stmt in created)

    altered = role_statements(
        owner_password="o",
        reader_password="r",
        signer_password="s",
        existing=frozenset({SIGNER_ROLE}),
    )
    assert any(stmt.startswith(f'ALTER ROLE "{SIGNER_ROLE}"') for stmt in altered)

    schema = "\n".join(schema_statements())
    assert f'GRANT USAGE ON SCHEMA "acl" TO {ident(SIGNER_ROLE)}' in schema
    assert f'GRANT USAGE ON SCHEMA "entity_access" TO {ident(SIGNER_ROLE)}' not in schema
    assert f'GRANT USAGE ON SCHEMA "entity_data" TO {ident(SIGNER_ROLE)}' not in schema
    assert f'REVOKE ALL ON SCHEMA "entity_data"' in schema
    assert SIGNER_ROLE in schema

    acl = acl_statements(pgcrypto_schema=None)
    signing_grants = [
        stmt
        for stmt in acl
        if stmt.startswith("GRANT EXECUTE ON FUNCTION acl.ensure_signing_key()")
    ]
    assert any(SIGNER_ROLE in stmt for stmt in signing_grants)
    assert any(ENTITY_OWNER_ROLE in stmt for stmt in signing_grants)
    assert not any(
        stmt.startswith("GRANT EXECUTE") and SIGNER_ROLE in stmt and "ensure_signing_key" not in stmt
        for stmt in acl
    )
    assert any(
        stmt.startswith("REVOKE ALL ON ALL TABLES IN SCHEMA") and SIGNER_ROLE in stmt
        for stmt in acl
    )

    connect = "\n".join(database_statements("refraq_entity", has_public_schema=True))
    assert f"GRANT CONNECT ON DATABASE {ident('refraq_entity')}" in connect
    assert SIGNER_ROLE in connect
    assert READER_ROLE in connect


def test_api_reader_url_message_names_the_persistent_api() -> None:
    set_process_role("api")
    with pytest.raises(ValueError, match="persistent API requires ENTITY_READER_DATABASE_URL"):
        require_entity_reader_database_url(None, owner_url=_OWNER)


def test_entity_mcp_reader_url_message_does_not_say_persistent_api() -> None:
    set_process_role("entity_mcp")
    reset_runtime_capacity()
    try:
        with pytest.raises(ValueError, match="ENTITY_READER_DATABASE_URL") as raised:
            require_entity_reader_database_url(None, owner_url=None)
        assert "persistent API" not in str(raised.value)
    finally:
        set_process_role("api")
        reset_runtime_capacity()


class _Settings:
    def __init__(self, *, reader: str | None, signer: str | None) -> None:
        self.store_backend = "persistent"
        self.entity_database_url = None
        self.entity_reader_database_url = reader
        self.entity_signer_database_url = signer
        self.database_url = _METADATA


class _Login:
    def __init__(self, superuser: bool, bypass: bool) -> None:
        self._row = (superuser, bypass)

    def connect(self) -> "_Login":
        return self

    def __enter__(self) -> "_Login":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, _sql: object) -> "_Login":
        return self

    def one(self) -> tuple[bool, bool]:
        return self._row

    def dispose(self) -> None:
        return None


def _entity_mcp(monkeypatch: pytest.MonkeyPatch, settings: _Settings) -> None:
    set_process_role("entity_mcp")
    reset_runtime_capacity()
    monkeypatch.setattr("backend.entity.entity_db.get_settings", lambda: settings)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_engine",
        lambda: (_ for _ in ()).throw(AssertionError("owner engine constructed")),
    )


def _restore_api() -> None:
    set_process_role("api")
    reset_runtime_capacity()


def test_entity_mcp_refuses_a_missing_signer_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _entity_mcp(monkeypatch, _Settings(reader=_READER, signer=None))
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_reader_engine",
        lambda: _Login(False, False),
    )
    try:
        with pytest.raises(ValueError, match="ENTITY_SIGNER_DATABASE_URL"):
            open_entity_reader_pool_when_persistent()
    finally:
        _restore_api()


def test_entity_mcp_refuses_a_signer_database_other_than_the_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _entity_mcp(monkeypatch, _Settings(reader=_READER, signer=_OTHER))
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_reader_engine",
        lambda: _Login(False, False),
    )
    try:
        with pytest.raises(ValueError, match="same database") as raised:
            open_entity_reader_pool_when_persistent()
        assert "ENTITY_SIGNER_DATABASE_URL" in str(raised.value)
        assert "ENTITY_READER_DATABASE_URL" in str(raised.value)
    finally:
        _restore_api()


@pytest.mark.parametrize(
    ("superuser", "bypass", "message"),
    [(True, False, "superuser"), (False, True, "BYPASSRLS")],
)
def test_entity_mcp_refuses_a_privileged_signer_login(
    monkeypatch: pytest.MonkeyPatch, superuser: bool, bypass: bool, message: str
) -> None:
    _entity_mcp(monkeypatch, _Settings(reader=_READER, signer=_SIGNER))
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_reader_engine",
        lambda: _Login(False, False),
    )
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_signer_engine",
        lambda: _Login(superuser, bypass),
    )
    try:
        with pytest.raises(ValueError, match=message):
            open_entity_reader_pool_when_persistent()
    finally:
        _restore_api()


def test_signer_pool_has_one_connection_and_no_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _entity_mcp(monkeypatch, _Settings(reader=_READER, signer=_SIGNER))
    captured: dict[str, object] = {}

    def _capture(url: str, **kwargs: object) -> _Login:
        captured["url"] = url
        captured["pool_size"] = kwargs.get("pool_size")
        captured["max_overflow"] = kwargs.get("max_overflow")
        return _Login(False, False)

    monkeypatch.setattr("backend.entity.entity_db.create_engine", _capture)
    get_entity_signer_engine.cache_clear()
    try:
        get_entity_signer_engine()
        assert captured["url"] == _SIGNER
        assert captured["pool_size"] == 1
        assert captured["max_overflow"] == 0
    finally:
        get_entity_signer_engine.cache_clear()
        _restore_api()


class _KeyConn:
    def __init__(self, secret: bytes) -> None:
        self.secret = secret
        self.statements: list[str] = []
        self.committed = False

    def execute(self, sql: object) -> "_KeyConn":
        self.statements.append(str(sql))
        return self

    def one(self) -> tuple[str, bytes]:
        return ("kid-1", self.secret)

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> "_KeyConn":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


class _KeyEngine:
    def __init__(self, secret: bytes) -> None:
        self.conn = _KeyConn(secret)

    def connect(self) -> _KeyConn:
        return self.conn


def _read_access() -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    person = Person("user_1", "role_1", ())
    policy = Policy(
        entity_id="ent_1",
        table_name="material",
        revision=3,
        source_sql='entity_data."material"',
        head_version_id="ver",
        attributes=(AttrFact("att_sku", "sku", "string"),),
        ladders={},
        profiles=(ProfileSpec("p_sku", "sku", (("att_sku", "clear"),)),),
        grants=(
            GrantSpec(
                "g1", "user", "user_1", "p_sku", None, frozenset({"read"}), "active", None
            ),
        ),
        restrictions=(),
        people=(person,),
        subject_attrs={},
        subject_values={},
        cap=64,
        existing_combos=frozenset(),
        now=now,
    )
    return SimpleNamespace(
        policy=policy,
        compiled=compile_policy(policy),
        person=person,
        action="read",
        narrow=None,
    )


def _payload(token: str) -> dict[str, object]:
    body = token.split(".", 1)[0]
    return json.loads(base64.b64decode(body))


def test_entity_mcp_signs_from_the_signer_pool_without_the_owner_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = bytes(range(32))
    engine = _KeyEngine(secret)
    set_process_role("entity_mcp")
    reset_runtime_capacity()
    reset_signing_ring()
    monkeypatch.setattr(
        "backend.entity.access.enforce.get_settings",
        lambda: SimpleNamespace(store_backend="persistent"),
    )
    monkeypatch.setattr(
        "backend.entity.access.enforce.get_entity_engine",
        lambda: (_ for _ in ()).throw(AssertionError("owner engine constructed")),
    )
    monkeypatch.setattr(
        "backend.entity.access.enforce.get_entity_signer_engine", lambda: engine
    )
    try:
        token = read_context(_read_access())
        assert token is not None
        assert _payload(token)["kid"] == "kid-1"
        assert _payload(token)["grants"] == ["g1"]
        assert any("acl.ensure_signing_key" in item for item in engine.conn.statements)
        assert engine.conn.committed
    finally:
        reset_signing_ring()
        set_process_role("api")
        reset_runtime_capacity()


def test_api_still_signs_from_the_owner_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = bytes(range(32))
    engine = _KeyEngine(secret)
    set_process_role("api")
    reset_runtime_capacity()
    reset_signing_ring()
    monkeypatch.setattr(
        "backend.entity.access.enforce.get_settings",
        lambda: SimpleNamespace(store_backend="persistent"),
    )
    monkeypatch.setattr("backend.entity.access.enforce.get_entity_engine", lambda: engine)
    monkeypatch.setattr(
        "backend.entity.access.enforce.get_entity_signer_engine",
        lambda: (_ for _ in ()).throw(AssertionError("signer engine constructed")),
    )
    try:
        token = read_context(_read_access())
        assert token is not None
        assert _payload(token)["kid"] == "kid-1"
        assert engine.conn.committed
    finally:
        reset_signing_ring()
        reset_runtime_capacity()


def test_entity_mcp_startup_aborts_when_the_signer_url_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.entity.mcp.http import ensure_entity_reader_pool_or_abort

    _entity_mcp(monkeypatch, _Settings(reader=_READER, signer=None))
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_reader_engine",
        lambda: _Login(False, False),
    )
    try:
        with pytest.raises(SystemExit) as aborted:
            ensure_entity_reader_pool_or_abort()
        assert aborted.value.code == 1
        assert "ENTITY_SIGNER_DATABASE_URL" in capsys.readouterr().err
    finally:
        _restore_api()
