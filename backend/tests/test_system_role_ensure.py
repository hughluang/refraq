"""Foundation Upgrade: System Role ensure (super_admin) vs Bootstrap seed."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.admin.permissions import ALL_PERMISSIONS
from backend.admin.roles import (
    OPERATOR_DEFAULT_PERMISSIONS,
    OPERATOR_KEY,
    SUPER_ADMIN_ID,
    SUPER_ADMIN_KEY,
    SUPER_ADMIN_NAME,
    create_role,
    ensure_system_role,
    seed_roles,
)
from backend.repositories.role_store import MemoryRoleStore, RoleRecord


def test_ensure_aligns_stale_super_admin_permissions() -> None:
    store = MemoryRoleStore()
    store.insert(
        RoleRecord(
            id=SUPER_ADMIN_ID,
            key=SUPER_ADMIN_KEY,
            name=SUPER_ADMIN_NAME,
            permissions=["console:access", "dashboard:read", "users:read"],
            locked=True,
        )
    )
    store.insert(
        RoleRecord(
            id="role_operator",
            key=OPERATOR_KEY,
            name="Operator",
            permissions=["console:access", "dashboard:read", "users:read"],
            locked=False,
        )
    )

    result = ensure_system_role(store)

    assert result.key == SUPER_ADMIN_KEY
    assert result.locked is True
    assert result.name == SUPER_ADMIN_NAME
    assert result.permissions == list(ALL_PERMISSIONS)
    assert "settings:read" in result.permissions
    assert "settings:write" in result.permissions
    assert "tokens:read" in result.permissions
    assert "tokens:write" in result.permissions
    assert "audit:read" in result.permissions
    assert "sources:read" in result.permissions
    assert "ingestion:run" in result.permissions

    operator = store.get_by_key(OPERATOR_KEY)
    assert operator is not None
    assert operator.permissions == [
        "console:access",
        "dashboard:read",
        "users:read",
    ]


def test_ensure_creates_missing_super_admin() -> None:
    store = MemoryRoleStore()
    store.insert(
        RoleRecord(
            id="role_operator",
            key=OPERATOR_KEY,
            name="Operator",
            permissions=list(OPERATOR_DEFAULT_PERMISSIONS),
            locked=False,
        )
    )

    result = ensure_system_role(store)

    assert result.id == SUPER_ADMIN_ID
    assert result.permissions == list(ALL_PERMISSIONS)
    assert result.locked is True
    assert store.get_by_key(OPERATOR_KEY) is not None


def test_ensure_does_not_change_custom_role() -> None:
    store = MemoryRoleStore()
    store.insert(
        RoleRecord(
            id=SUPER_ADMIN_ID,
            key=SUPER_ADMIN_KEY,
            name="Renamed",
            permissions=["console:access"],
            locked=False,
        )
    )
    custom = create_role(
        store,
        key="analyst",
        name="Analyst",
        permissions=["console:access", "dashboard:read"],
    )

    ensure_system_role(store)

    refreshed = store.get_by_id(custom.id)
    assert refreshed is not None
    assert refreshed.permissions == ["console:access", "dashboard:read"]
    super_admin = store.get_by_key(SUPER_ADMIN_KEY)
    assert super_admin is not None
    assert super_admin.locked is True
    assert super_admin.name == SUPER_ADMIN_NAME


def test_seed_roles_insert_once_does_not_realign() -> None:
    store = MemoryRoleStore()
    seed_roles(store)
    stale = store.get_by_key(SUPER_ADMIN_KEY)
    assert stale is not None
    stale.permissions = ["console:access"]

    seed_roles(store)

    after = store.get_by_key(SUPER_ADMIN_KEY)
    assert after is not None
    assert after.permissions == ["console:access"]


def test_run_upgrade_calls_ensure_after_migrate() -> None:
    from backend.core import upgrade as upgrade_mod

    calls: list[str] = []

    def fake_upgrade(cfg: object, rev: str) -> None:
        calls.append(f"migrate:{rev}")

    def fake_ensure(_roles: object) -> RoleRecord:
        calls.append("ensure")
        return RoleRecord(
            id=SUPER_ADMIN_ID,
            key=SUPER_ADMIN_KEY,
            name=SUPER_ADMIN_NAME,
            permissions=list(ALL_PERMISSIONS),
            locked=True,
        )

    mock_conn = MagicMock()
    mock_conn.execute.return_value.scalar.side_effect = [True, None]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.connect.return_value.__exit__.return_value = None

    with (
        patch.object(upgrade_mod, "create_engine", return_value=mock_engine),
        patch.object(upgrade_mod.command, "upgrade", side_effect=fake_upgrade),
        patch.object(upgrade_mod, "ensure_system_role", side_effect=fake_ensure),
    ):
        upgrade_mod.run_upgrade("postgresql://example/db")

    assert calls == ["migrate:head", "ensure"]


def test_migrate_only_skips_ensure() -> None:
    from backend.core import upgrade as upgrade_mod

    calls: list[str] = []

    def fake_upgrade(cfg: object, rev: str) -> None:
        calls.append("migrate")

    mock_conn = MagicMock()
    mock_conn.execute.return_value.scalar.side_effect = [True, None]
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__.return_value = mock_conn
    mock_engine.connect.return_value.__exit__.return_value = None

    with (
        patch.object(upgrade_mod, "create_engine", return_value=mock_engine),
        patch.object(upgrade_mod.command, "upgrade", side_effect=fake_upgrade),
        patch.object(
            upgrade_mod,
            "ensure_system_role",
            side_effect=AssertionError("ensure must not run"),
        ),
    ):
        upgrade_mod.migrate_with_advisory_lock("postgresql://example/db")

    assert calls == ["migrate"]


def test_entry_exits_without_serve_when_upgrade_fails() -> None:
    from backend.core import entry as entry_mod
    from backend.core.config import Settings

    fake_settings = Settings(
        store_backend="persistent",
        database_url="postgresql://example/db",
        redis_url="redis://example/0",
        initial_admin_account="root",
        initial_admin_password="root",
    )

    with (
        patch.object(entry_mod, "get_settings", return_value=fake_settings),
        patch.object(
            entry_mod,
            "run_upgrade",
            side_effect=RuntimeError("boom"),
        ),
        patch.dict("sys.modules", {"uvicorn": MagicMock()}),
    ):
        with pytest.raises(SystemExit) as exc_info:
            entry_mod.main()
        assert exc_info.value.code == 1
        import uvicorn

        uvicorn.run.assert_not_called()
