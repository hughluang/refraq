"""Entity database URL rules and the unprivileged-role startup check."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.core.config import (
    require_distinct_entity_database,
    require_entity_reader_database_url,
)
from backend.core.runtime import reset_runtime_capacity, set_process_role
from backend.entity.ddl import ENTITY_SCHEMAS
from backend.entity.entity_db import (
    get_entity_engine,
    get_entity_reader_engine,
    open_entity_reader_pool_when_persistent,
    require_entity_schemas,
    require_unprivileged_role,
)


def test_entity_database_must_differ_from_metadata() -> None:
    owner = "postgresql+psycopg://refraq_entity_owner:pw@127.0.0.1:5432/refraq_entity"
    require_distinct_entity_database(
        owner, "postgresql+psycopg://refraq:pw@localhost:5432/refraq"
    )
    with pytest.raises(ValueError, match="ENTITY_DATABASE_URL"):
        require_distinct_entity_database(
            owner, "postgresql+psycopg://refraq:pw@localhost:5432/refraq_entity"
        )


def test_reader_url_is_required_and_names_the_owner_database() -> None:
    owner = "postgresql+psycopg://refraq_entity_owner:pw@127.0.0.1:5432/refraq_entity"
    reader = "postgresql+psycopg://refraq_reader:pw@localhost:5432/refraq_entity"
    assert require_entity_reader_database_url(reader, owner_url=owner) == reader
    with pytest.raises(ValueError, match="ENTITY_READER_DATABASE_URL"):
        require_entity_reader_database_url(None, owner_url=owner)
    with pytest.raises(ValueError, match="same database"):
        require_entity_reader_database_url(
            "postgresql+psycopg://refraq_reader:pw@127.0.0.1:5432/other",
            owner_url=owner,
        )


class _Role:
    def __init__(self, superuser: bool, bypass: bool) -> None:
        self._row = (superuser, bypass)

    def execute(self, _sql: object) -> "_Role":
        return self

    def one(self) -> tuple[bool, bool]:
        return self._row


def test_runtime_role_must_not_be_superuser() -> None:
    with pytest.raises(ValueError, match="superuser"):
        require_unprivileged_role(_Role(True, False), "ENTITY_DATABASE_URL")
    require_unprivileged_role(_Role(False, False), "ENTITY_DATABASE_URL")


def test_reader_role_must_not_bypass_rls() -> None:
    with pytest.raises(ValueError, match="BYPASSRLS"):
        require_unprivileged_role(
            _Role(False, True), "ENTITY_READER_DATABASE_URL", reader=True
        )
    require_unprivileged_role(
        _Role(False, False), "ENTITY_READER_DATABASE_URL", reader=True
    )


class _Schemas:
    def __init__(self, names: tuple[str, ...]) -> None:
        self._names = names

    def execute(self, _sql: object) -> "_Schemas":
        return self

    def __iter__(self) -> Iterator[tuple[str]]:
        return iter((name,) for name in self._names)


def test_entity_schemas_pass_when_all_four_are_present() -> None:
    require_entity_schemas(_Schemas(ENTITY_SCHEMAS))


def test_missing_channel_dataset_names_the_bootstrap_command() -> None:
    present = tuple(name for name in ENTITY_SCHEMAS if name != "channel_dataset")
    with pytest.raises(ValueError, match="channel_dataset") as raised:
        require_entity_schemas(_Schemas(present))
    message = str(raised.value)
    assert "python -m backend.entity.bootstrap" in message
    assert "entity_data" not in message
    assert "entity_access" not in message
    assert "acl" not in message


_OWNER = "postgresql+psycopg://refraq_entity_owner:pw@127.0.0.1:5432/refraq_entity"
_READER = "postgresql+psycopg://refraq_reader:pw@127.0.0.1:5432/refraq_entity"
_SIGNER = "postgresql+psycopg://refraq_signer:pw@127.0.0.1:5432/refraq_entity"
_METADATA = "postgresql+psycopg://refraq:pw@127.0.0.1:5432/refraq"
_OWNER_ON_METADATA = "postgresql+psycopg://refraq_entity_owner:pw@127.0.0.1:5432/refraq"
_READER_ON_METADATA = "postgresql+psycopg://refraq_reader:pw@127.0.0.1:5432/refraq"


class _PersistentSettings:
    def __init__(
        self,
        *,
        entity_database_url: str | None,
        entity_reader_database_url: str | None,
        database_url: str | None,
        entity_signer_database_url: str | None = None,
    ) -> None:
        self.store_backend = "persistent"
        self.entity_database_url = entity_database_url
        self.entity_reader_database_url = entity_reader_database_url
        self.entity_signer_database_url = entity_signer_database_url
        self.database_url = database_url


class _ReaderEngine:
    def __init__(self, superuser: bool, bypass: bool) -> None:
        self._row = (superuser, bypass)

    def connect(self) -> "_ReaderEngine":
        return self

    def __enter__(self) -> "_ReaderEngine":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def execute(self, _sql: object) -> "_ReaderEngine":
        return self

    def one(self) -> tuple[bool, bool]:
        return self._row

    def dispose(self) -> None:
        return None


def _refuse_owner_engine() -> None:
    raise AssertionError("owner engine constructed")


def _use_entity_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    set_process_role("entity_mcp")
    reset_runtime_capacity()
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_engine", _refuse_owner_engine
    )


def _restore_api_role() -> None:
    set_process_role("api")
    reset_runtime_capacity()


def test_entity_mcp_reader_startup_is_noop_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_entity_mcp(monkeypatch)
    try:
        open_entity_reader_pool_when_persistent()
    finally:
        _restore_api_role()


@pytest.mark.parametrize("owner_url", [None, "   "])
def test_entity_mcp_reader_startup_allows_missing_owner_url(
    monkeypatch: pytest.MonkeyPatch, owner_url: str | None
) -> None:
    _use_entity_mcp(monkeypatch)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=owner_url,
            entity_reader_database_url=_READER,
            entity_signer_database_url=_SIGNER,
            database_url=_METADATA,
        ),
    )
    created: list[str] = []

    def _capture(url: str, **_kwargs: object) -> _ReaderEngine:
        created.append(url)
        return _ReaderEngine(False, False)

    get_entity_reader_engine.cache_clear()
    monkeypatch.setattr("backend.entity.entity_db.create_engine", _capture)
    try:
        open_entity_reader_pool_when_persistent()
        assert created == [_READER, _SIGNER]
    finally:
        get_entity_reader_engine.cache_clear()
        _restore_api_role()


def test_entity_mcp_reader_startup_requires_reader_url_without_owner_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_entity_mcp(monkeypatch)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=None,
            entity_reader_database_url=None,
            database_url=_METADATA,
        ),
    )
    try:
        with pytest.raises(ValueError, match="ENTITY_READER_DATABASE_URL") as raised:
            open_entity_reader_pool_when_persistent()
        assert "ENTITY_DATABASE_URL to open the entity pool" not in str(raised.value)
    finally:
        _restore_api_role()


def test_entity_mcp_reader_startup_refuses_metadata_database_without_owner_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_entity_mcp(monkeypatch)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=None,
            entity_reader_database_url=_READER_ON_METADATA,
            database_url=_METADATA,
        ),
    )
    try:
        with pytest.raises(ValueError, match="other than DATABASE_URL"):
            open_entity_reader_pool_when_persistent()
    finally:
        _restore_api_role()


def test_entity_mcp_reader_startup_requires_same_database_when_owner_url_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_entity_mcp(monkeypatch)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=_OWNER,
            entity_reader_database_url=(
                "postgresql+psycopg://refraq_reader:pw@127.0.0.1:5432/other_entity"
            ),
            database_url=_METADATA,
        ),
    )
    try:
        with pytest.raises(ValueError, match="same database") as raised:
            open_entity_reader_pool_when_persistent()
        assert "ENTITY_DATABASE_URL" in str(raised.value)
    finally:
        _restore_api_role()


def test_entity_mcp_reader_startup_requires_reader_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_entity_mcp(monkeypatch)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=_OWNER,
            entity_reader_database_url=None,
            database_url=_METADATA,
        ),
    )
    try:
        with pytest.raises(ValueError, match="ENTITY_READER_DATABASE_URL"):
            open_entity_reader_pool_when_persistent()
    finally:
        _restore_api_role()


def test_entity_mcp_reader_startup_refuses_metadata_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_entity_mcp(monkeypatch)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=_OWNER_ON_METADATA,
            entity_reader_database_url=_READER_ON_METADATA,
            database_url=_METADATA,
        ),
    )
    try:
        with pytest.raises(ValueError, match="DATABASE_URL"):
            open_entity_reader_pool_when_persistent()
    finally:
        _restore_api_role()


def test_entity_mcp_reader_startup_refuses_superuser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_entity_mcp(monkeypatch)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=_OWNER,
            entity_reader_database_url=_READER,
            database_url=_METADATA,
        ),
    )
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_reader_engine",
        lambda: _ReaderEngine(True, False),
    )
    try:
        with pytest.raises(ValueError, match="superuser"):
            open_entity_reader_pool_when_persistent()
    finally:
        _restore_api_role()


def test_entity_mcp_reader_startup_refuses_bypassrls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_entity_mcp(monkeypatch)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=_OWNER,
            entity_reader_database_url=_READER,
            database_url=_METADATA,
        ),
    )
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_reader_engine",
        lambda: _ReaderEngine(False, True),
    )
    try:
        with pytest.raises(ValueError, match="BYPASSRLS"):
            open_entity_reader_pool_when_persistent()
    finally:
        _restore_api_role()


def test_entity_mcp_reader_startup_does_not_construct_owner_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_entity_mcp(monkeypatch)
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=_OWNER,
            entity_reader_database_url=_READER,
            entity_signer_database_url=_SIGNER,
            database_url=_METADATA,
        ),
    )
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_reader_engine",
        lambda: _ReaderEngine(False, False),
    )
    monkeypatch.setattr(
        "backend.entity.entity_db.get_entity_signer_engine",
        lambda: _ReaderEngine(False, False),
    )
    try:
        open_entity_reader_pool_when_persistent()
    finally:
        _restore_api_role()


def test_entity_mcp_reader_gate_aborts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from backend.entity.mcp.http import ensure_entity_reader_pool_or_abort

    set_process_role("entity_mcp")
    reset_runtime_capacity()
    monkeypatch.setattr(
        "backend.entity.entity_db.get_settings",
        lambda: _PersistentSettings(
            entity_database_url=_OWNER,
            entity_reader_database_url=None,
            database_url=_METADATA,
        ),
    )
    try:
        with pytest.raises(SystemExit) as aborted:
            ensure_entity_reader_pool_or_abort()
        assert aborted.value.code == 1
        assert "ENTITY_READER_DATABASE_URL" in capsys.readouterr().err
    finally:
        _restore_api_role()


def test_entity_mcp_role_does_not_construct_owner_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_process_role("entity_mcp")
    reset_runtime_capacity()
    created: list[str] = []

    def _capture(url: str, **_kwargs: object) -> object:
        created.append(url)
        raise AssertionError("create_engine")

    monkeypatch.setattr("backend.entity.entity_db.create_engine", _capture)
    try:
        with pytest.raises(RuntimeError, match="owner engine"):
            get_entity_engine()
        assert created == []
    finally:
        _restore_api_role()
