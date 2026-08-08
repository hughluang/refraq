"""User repository ports and adapters for the Management Foundation."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Literal, Protocol

from backend.admin.locales import DEFAULT_LOCALE
from backend.core.config import get_settings

UserStatus = Literal["active", "disabled"]
IdentitySource = Literal["local"]


@dataclass
class UserRecord:
    id: str
    account: str
    display_name: str
    password_hash: str
    role_id: str | None
    status: UserStatus
    identity_source: IdentitySource = "local"
    email: str | None = None
    locale: str = DEFAULT_LOCALE
    last_login_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class UserStore(Protocol):
    def count(self) -> int: ...

    def get_by_id(self, user_id: str) -> UserRecord | None: ...

    def get_by_account(self, account: str) -> UserRecord | None: ...

    def list_users(self) -> list[UserRecord]: ...

    def count_by_role_id(self, role_id: str) -> int: ...

    def create_user(
        self,
        *,
        account: str,
        display_name: str,
        password_hash: str,
        role_id: str | None,
        status: UserStatus = "active",
        identity_source: IdentitySource = "local",
        email: str | None = None,
        locale: str = DEFAULT_LOCALE,
    ) -> UserRecord: ...

    def update_status(self, user_id: str, status: UserStatus) -> UserRecord | None: ...

    def update_last_login(self, user_id: str, when: datetime) -> None: ...

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        email: str | None = None,
        set_email: bool = False,
        locale: str | None = None,
    ) -> UserRecord | None: ...

    def update_password_hash(self, user_id: str, password_hash: str) -> UserRecord | None: ...


class MemoryUserStore:
    def __init__(self) -> None:
        self._by_id: dict[str, UserRecord] = {}
        self._by_account: dict[str, str] = {}
        self._lock = threading.Lock()

    def count(self) -> int:
        with self._lock:
            return len(self._by_id)

    def get_by_id(self, user_id: str) -> UserRecord | None:
        with self._lock:
            return self._by_id.get(user_id)

    def get_by_account(self, account: str) -> UserRecord | None:
        with self._lock:
            user_id = self._by_account.get(account)
            if user_id is None:
                return None
            return self._by_id.get(user_id)

    def list_users(self) -> list[UserRecord]:
        with self._lock:
            return sorted(
                self._by_id.values(),
                key=lambda record: (record.created_at, record.id),
            )

    def count_by_role_id(self, role_id: str) -> int:
        with self._lock:
            return sum(1 for record in self._by_id.values() if record.role_id == role_id)

    def create_user(
        self,
        *,
        account: str,
        display_name: str,
        password_hash: str,
        role_id: str | None,
        status: UserStatus = "active",
        identity_source: IdentitySource = "local",
        email: str | None = None,
        locale: str = DEFAULT_LOCALE,
    ) -> UserRecord:
        with self._lock:
            if account in self._by_account:
                from backend.admin.errors import UserAccountDuplicate

                raise UserAccountDuplicate()
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            record = UserRecord(
                id=user_id,
                account=account,
                display_name=display_name,
                password_hash=password_hash,
                role_id=role_id,
                status=status,
                identity_source=identity_source,
                email=email,
                locale=locale,
            )
            self._by_id[user_id] = record
            self._by_account[account] = user_id
            return record

    def update_status(self, user_id: str, status: UserStatus) -> UserRecord | None:
        with self._lock:
            record = self._by_id.get(user_id)
            if record is None:
                return None
            record.status = status
            return record

    def update_last_login(self, user_id: str, when: datetime) -> None:
        with self._lock:
            record = self._by_id.get(user_id)
            if record is not None:
                record.last_login_at = when

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        email: str | None = None,
        set_email: bool = False,
        locale: str | None = None,
    ) -> UserRecord | None:
        with self._lock:
            record = self._by_id.get(user_id)
            if record is None:
                return None
            if display_name is not None:
                record.display_name = display_name
            if set_email:
                record.email = email
            if locale is not None:
                record.locale = locale
            return record

    def update_password_hash(self, user_id: str, password_hash: str) -> UserRecord | None:
        with self._lock:
            record = self._by_id.get(user_id)
            if record is None:
                return None
            record.password_hash = password_hash
            return record


class SqlUserStore:
    def count(self) -> int:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow

        with session_scope() as session:
            return session.query(UserRow).count()

    def get_by_id(self, user_id: str) -> UserRecord | None:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow

        with session_scope() as session:
            row = session.get(UserRow, user_id)
            return _row_to_user(row) if row else None

    def get_by_account(self, account: str) -> UserRecord | None:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow
        from sqlalchemy import select

        with session_scope() as session:
            row = session.scalar(select(UserRow).where(UserRow.account == account))
            return _row_to_user(row) if row else None

    def list_users(self) -> list[UserRecord]:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow
        from sqlalchemy import select

        with session_scope() as session:
            rows = session.scalars(
                select(UserRow).order_by(UserRow.created_at, UserRow.id)
            ).all()
            return [_row_to_user(row) for row in rows]

    def count_by_role_id(self, role_id: str) -> int:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow
        from sqlalchemy import func, select

        with session_scope() as session:
            return int(
                session.scalar(
                    select(func.count()).select_from(UserRow).where(UserRow.role_id == role_id)
                )
                or 0
            )

    def create_user(
        self,
        *,
        account: str,
        display_name: str,
        password_hash: str,
        role_id: str | None,
        status: UserStatus = "active",
        identity_source: IdentitySource = "local",
        email: str | None = None,
        locale: str = DEFAULT_LOCALE,
    ) -> UserRecord:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        user_id = f"user_{uuid.uuid4().hex[:12]}"
        created_at = datetime.utcnow()
        try:
            with session_scope() as session:
                existing = session.scalar(select(UserRow).where(UserRow.account == account))
                if existing is not None:
                    from backend.admin.errors import UserAccountDuplicate

                    raise UserAccountDuplicate()
                row = UserRow(
                    id=user_id,
                    account=account,
                    display_name=display_name,
                    email=email,
                    locale=locale,
                    password_hash=password_hash,
                    role_id=role_id,
                    status=status,
                    identity_source=identity_source,
                    created_at=created_at,
                )
                session.add(row)
                session.flush()
                return _row_to_user(row)
        except IntegrityError as exc:
            from backend.admin.errors import UserAccountDuplicate

            raise UserAccountDuplicate() from exc

    def update_status(self, user_id: str, status: UserStatus) -> UserRecord | None:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow

        with session_scope() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                return None
            row.status = status
            session.flush()
            return _row_to_user(row)

    def update_last_login(self, user_id: str, when: datetime) -> None:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow

        with session_scope() as session:
            row = session.get(UserRow, user_id)
            if row is not None:
                row.last_login_at = when

    def update_profile(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        email: str | None = None,
        set_email: bool = False,
        locale: str | None = None,
    ) -> UserRecord | None:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow

        with session_scope() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                return None
            if display_name is not None:
                row.display_name = display_name
            if set_email:
                row.email = email
            if locale is not None:
                row.locale = locale
            session.flush()
            return _row_to_user(row)

    def update_password_hash(self, user_id: str, password_hash: str) -> UserRecord | None:
        from backend.core.db import session_scope
        from backend.admin.models import UserRow

        with session_scope() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                return None
            row.password_hash = password_hash
            session.flush()
            return _row_to_user(row)


def _row_to_user(row: object) -> UserRecord:
    from backend.admin.models import UserRow

    assert isinstance(row, UserRow)
    return UserRecord(
        id=row.id,
        account=row.account,
        display_name=row.display_name,
        password_hash=row.password_hash,
        role_id=row.role_id,
        status=row.status,  # type: ignore[arg-type]
        identity_source=row.identity_source,  # type: ignore[arg-type]
        email=row.email,
        locale=row.locale or DEFAULT_LOCALE,
        last_login_at=row.last_login_at,
        created_at=row.created_at,
    )


# Back-compat alias used by tests that construct MemoryUserStore as UserStore historically
UserStoreImpl = MemoryUserStore


_memory_singleton: MemoryUserStore | None = None
_memory_lock = threading.Lock()


@lru_cache
def get_user_store() -> UserStore:
    settings = get_settings()
    if settings.store_backend == "memory":
        global _memory_singleton
        with _memory_lock:
            if _memory_singleton is None:
                _memory_singleton = MemoryUserStore()
            return _memory_singleton
    return SqlUserStore()


def reset_user_store() -> None:
    global _memory_singleton
    with _memory_lock:
        _memory_singleton = None
    get_user_store.cache_clear()
