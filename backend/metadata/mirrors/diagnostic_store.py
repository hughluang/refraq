"""Bounded diagnostics history and independently written latest observations."""

from copy import deepcopy
from threading import RLock

from sqlalchemy import JSON, String, select, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.db import Base


class DiagnosticRow(Base):
    __tablename__ = "source_mirror_diagnostics"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)


class DiagnosticStore:
    def __init__(self, *, memory, transaction):
        self.memory = memory
        self.transaction = transaction
        self.values = {}
        self.lock = RLock()

    def read(self, kind, scope_id):
        key = f"{kind}:{scope_id}"
        if self.memory:
            with self.lock:
                return deepcopy(self.values.get(key))
        with self.transaction() as session:
            return session.scalar(select(DiagnosticRow.value).where(DiagnosticRow.id == key))

    def all(self, kind):
        if self.memory:
            with self.lock:
                prefix = kind + ":"
                return {key[len(prefix):]: deepcopy(value) for key, value in self.values.items() if key.startswith(prefix)}
        with self.transaction() as session:
            return dict(session.execute(select(DiagnosticRow.scope_id, DiagnosticRow.value).where(DiagnosticRow.kind == kind)).all())

    def update(self, kind, scope_id, change):
        """Serialize only this telemetry key; never acquire Source or target locks."""
        key = f"{kind}:{scope_id}"
        if self.memory:
            with self.lock:
                value = change(deepcopy(self.values.get(key)))
                self.values[key] = deepcopy(value)
                return value
        with self.transaction() as session:
            if session.get_bind().dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": "diagnostics:" + key})
            row = session.get(DiagnosticRow, key)
            value = change(deepcopy(row.value) if row else None)
            if row:
                row.value = value
            else:
                session.add(DiagnosticRow(id=key, kind=kind, scope_id=scope_id, value=value))
            return value
