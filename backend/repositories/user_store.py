"""In-memory User repository for the Management Foundation."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

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
    last_login_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class UserStore:
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


_store_singleton: UserStore | None = None
_store_lock = threading.Lock()


def get_user_store() -> UserStore:
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = UserStore()
        return _store_singleton


def reset_user_store() -> None:
    global _store_singleton
    with _store_lock:
        _store_singleton = None
