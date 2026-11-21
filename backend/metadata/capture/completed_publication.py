"""Publish completed PostgreSQL snapshots after the independent verifier seals them."""

from contextlib import contextmanager
from dataclasses import asdict

from sqlalchemy.exc import SQLAlchemyError

from backend.core.config import get_settings
from backend.core.db import get_session_factory
from backend.metadata.capture.runtime_store import RuntimeBlocked
from backend.metadata.mirrors.history import History, SqlHistoryTarget
from backend.metadata.mirrors.publication import Publication
from backend.metadata.mirrors.recovery import Recovery
from backend.metadata.mirrors.service import (
    MirrorError,
    OpenPublicationIdentity,
    publication_certificate_ref,
    reconcile_open_publication,
    validate_snapshot_completion,
)


def publish_completed(*, binding, command, delivery, result):
    """Consume a verified seal idempotently. An unsealed snapshot stays catching up."""
    publisher = Publication(delivery.engine, timeout_ms=delivery.settings["target"]["timeout_seconds"] * 1000)
    lookup = dict(operation_id=binding.allocation_operation_id, generation_id=binding.generation_id,
                  authority=binding.authority)
    try:
        certificate = publisher.verified_certificate(**lookup)
        if certificate is None:
            return False
        expected = OpenPublicationIdentity(
            binding.authority, binding.generation_id, binding.history_epoch, result.operation_id,
            result.scan_offset, result.completion_offset, publication_certificate_ref(certificate),
        )
        validate_snapshot_completion(certificate, qualified_table=binding.qualified_table, expected=expected,
                                     snapshot=asdict(binding))
        if command["kind"] == "replace_owner":
            delays = get_settings().mirror_recovery_retry_delays_seconds
            if not delays:
                raise RuntimeBlocked("recovery_retry_budget_required")
            sessions = get_session_factory()
            # Publication checks durable invalidation receipts in Management. Its
            # recovery path does not read rows or invoke a history gateway.
            history = History(session_factory=sessions, target=SqlHistoryTarget(
                engine=delivery.engine, invalidation_engine=delivery.engine, timeout_ms=publisher.timeout_ms))
            recovery = Recovery(session_factory=sessions, history=history, retry_delays=delays, publication=publisher)
            recovery.publish_replacement(operation_id=binding.allocation_operation_id,
                                         authority=binding.authority, certificate=certificate)
            return True

        @contextmanager
        def switch_and_observe(**request):
            # The management service holds the Source and Mirror locks from
            # current-intent validation through reconciliation of the pointer.
            publisher.publish_generation(**lookup, certificate=certificate)
            with publisher.observe_committed(**request) as observed:
                yield observed

        reconcile_open_publication(mirror_id=binding.mirror_id, operation_id=binding.allocation_operation_id,
                                   expected=expected, observe_committed=switch_and_observe)
        return True
    except (MirrorError, SQLAlchemyError, ValueError, KeyError, TypeError):
        raise RuntimeBlocked("publication_observation_rejected") from None
