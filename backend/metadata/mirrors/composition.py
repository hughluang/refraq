"""Assemble restricted Mirror adapters and explicit diagnostic dependencies."""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from backend.core.config import Settings, database_target
from backend.metadata.catalog.store import get_catalog_store
from backend.metadata.mirrors import fleet
from backend.metadata.mirrors.bootstrap import validate_target
from backend.metadata.mirrors.deletion import TargetDeletion
from backend.metadata.mirrors.diagnostic_store import DiagnosticStore
from backend.metadata.mirrors.history import SqlHistoryTarget
from backend.metadata.mirrors.errors import MirrorError
from backend.metadata.mirrors.presentation import diagnostic_scope
from backend.metadata.mirrors.service import storage
from backend.metadata.sources.store import get_source_store


def compose_diagnostics(settings: Settings, *, transaction):
    store = DiagnosticStore(memory=settings.store_backend == "memory", transaction=transaction)
    mirror_store, source_store = storage(), get_source_store()
    read_scope = partial(diagnostic_scope, mirror_store=mirror_store, source_store=source_store)
    dependencies = dict(store=store, mirror_store=mirror_store, source_store=source_store, catalog_store=get_catalog_store())
    fleet_reads = {name: partial(getattr(fleet, name), **dependencies)
                   for name in ("inventory", "overview", "sources", "runtimes")}
    return store, read_scope, fleet_reads


def _unavailable():
    raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)


class _ServingEngine:
    """Keep target exceptions and driver row details out of callers and logs."""

    def __init__(self, engine):
        self.engine = engine
        self.closed = False

    @contextmanager
    def begin(self):
        if self.closed:
            _unavailable()
        try:
            with self.engine.begin() as connection:
                yield connection
        except SQLAlchemyError:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503) from None

    def close(self):
        self.closed = True
        self.engine.dispose()


@dataclass
class MirrorAdapters:
    deletion: TargetDeletion
    history_target: SqlHistoryTarget
    gateway: _ServingEngine
    applier: _ServingEngine

    def close(self):
        self.gateway.close()
        self.applier.close()


def compose_mirrors(settings: Settings) -> MirrorAdapters | None:
    policy = settings.mirror_target
    if policy is None or settings.store_backend != "persistent":
        return None
    engines = []
    try:
        urls = (policy.gateway_url.get_secret_value(), policy.applier_url.get_secret_value())
        # Target state must never share the Management database.
        if settings.database_url and database_target(urls[0]) == database_target(settings.database_url):
            _unavailable()
        for url, role in zip(urls, ("refraq_mirror_gateway", "refraq_mirror_applier"), strict=True):
            engine = create_engine(
                url, poolclass=NullPool, hide_parameters=True, echo=False,
                connect_args={
                    "connect_timeout": policy.connect_timeout_seconds,
                    "options": f"-c statement_timeout={policy.timeout_ms} -c lock_timeout={policy.timeout_ms}",
                },
            )
            engines.append(engine)
            with engine.connect() as connection:
                validate_target(connection.connection.driver_connection, expected_role=role)
        gateway, applier = (_ServingEngine(engine) for engine in engines)
        target = SqlHistoryTarget(engine=gateway, invalidation_engine=applier, timeout_ms=policy.timeout_ms)
        target.validate()
        return MirrorAdapters(deletion=TargetDeletion(applier), history_target=target, gateway=gateway, applier=applier)
    except Exception:
        for engine in engines:
            engine.dispose()
        raise MirrorError("MIRROR_READ_UNAVAILABLE", 503) from None
