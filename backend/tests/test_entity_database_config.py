"""Entity database URL rules and the unprivileged-role startup check."""

from __future__ import annotations

import pytest

from backend.core.config import (
    require_distinct_entity_database,
    require_entity_reader_database_url,
)
from backend.entity.entity_db import require_unprivileged_role


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
