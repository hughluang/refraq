"""Fail-closed assembly of restricted mirror serving adapters; no runtime proofs."""

from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from backend.core.config import Settings, _database_target
from backend.metadata.mirrors.authorization import authorize_source_data
from backend.metadata.mirrors.bootstrap import validate_target
from backend.metadata.mirrors.history import SqlHistoryTarget
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.service import MirrorError


def _unavailable():
    raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)


def _deny_release(**_kwargs):
    # No trusted terminal/non-resumability proof adapter exists yet.
    _unavailable()


def terminal_proof_adapter(validator=None):
    """Composition injects Channel's authoritative terminal/non-resumable check.

    The validator must revalidate the exact run and proof against durable Channel
    state, raise on unknown/resumable runs and return None, never a boolean.
    """
    if validator is None:
        return _deny_release
    if not callable(validator):
        raise TypeError("Terminal proof validator must be callable")

    def verify(*, run_id, terminal_proof):
        if not isinstance(run_id, str) or not run_id or terminal_proof is None or isinstance(terminal_proof, bool):
            _unavailable()
        try:
            result = validator(run_id=run_id, terminal_proof=terminal_proof)
        except MirrorError:
            raise
        except Exception:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503) from None
        if result is not None:
            _unavailable()

    return verify


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
    reads: Reads
    history_target: SqlHistoryTarget
    gateway: _ServingEngine
    applier: _ServingEngine

    def close(self):
        self.gateway.close()
        self.applier.close()


def compose_mirrors(settings: Settings, *, verify_terminal_proof=None) -> MirrorAdapters | None:
    policy = settings.mirror_target
    if policy is None or settings.store_backend != "persistent":
        return None
    engines = []
    try:
        urls = (policy.gateway_url.get_secret_value(), policy.applier_url.get_secret_value())
        # Target state must never share the Management database.
        if settings.database_url and _database_target(urls[0]) == _database_target(settings.database_url):
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
        return MirrorAdapters(
            reads=Reads(gateway, authorize_source_read=authorize_source_data,
                        verify_terminal_proof=terminal_proof_adapter(verify_terminal_proof)),
            history_target=target, gateway=gateway, applier=applier,
        )
    except Exception:
        for engine in engines:
            engine.dispose()
        raise MirrorError("MIRROR_READ_UNAVAILABLE", 503) from None
