"""Dispatch an audited whole-Source replacement using a trusted loss observer."""

from datetime import datetime, timezone

from backend.metadata.capture.control import AUTHORITY_KEYS, included_tables, profile_matches_scope
from backend.metadata.capture.runtime_store import RuntimeBlocked
from backend.metadata.capture.store import load_binding
from backend.metadata.mirrors.composition import compose_mirrors
from backend.metadata.mirrors.history import History
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.recovery import Recovery, RuntimeDispatchAdapter
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.service import MirrorError


class ReplacementDispatch:
    def __init__(self, *, session_factory, operation_id, source_id, signals):
        self.session_factory = session_factory
        self.operation_id = operation_id
        self.source_id = source_id
        self.signals = signals

    def inspect(self, *, session, mirror, now):
        row = session.get(RecoveryRow, self.operation_id)
        gate = session.get(HistoryGateRow, mirror.id)
        binding = load_binding(session, self.source_id)
        if (row is None or row.source_id != self.source_id or row.mirror_id != mirror.id
                or mirror.source_id != self.source_id or gate is None or binding is None
                or binding.get("desired") != "configured" or binding.get("pending_replacement")):
            raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
        published_scope = binding.get("published_scope", [])
        if (not profile_matches_scope(self.signals.scope, published_scope)
                or [table["mirror_id"] for table in included_tables(published_scope)] != [mirror.id]):
            raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
        scope = dict(profile=self.signals.scope, mirror_id=mirror.id, table_identity=mirror.table_identity,
                     history_epoch=gate.history_epoch)
        authority = {key: binding[key] for key in AUTHORITY_KEYS}
        request = dict(authority=authority, scope=scope, operation_id=self.operation_id)
        try:
            result = self.signals.http.request("POST", "/v1/capture/recovery-loss-observations", request)
            claims = self.signals.verifier.verify(result["signature"], purpose="observation:recovery_loss", **request)
            observation = claims["observation"]
            observed = datetime.fromisoformat(observation["observed_at"])
            expires = datetime.fromtimestamp(claims["exp"], timezone.utc)
            if (observation["validity"] != "lost" or observed.tzinfo is None or observed >= expires
                    or (expires - observed).total_seconds() > self.signals.max_age):
                raise ValueError
        except (RuntimeBlocked, KeyError, ValueError, TypeError, OverflowError):
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503) from None
        return dict(source_id=self.source_id, mirror_id=mirror.id, table_identity=mirror.table_identity,
                    history_epoch=gate.history_epoch, validity="lost", affected_mirror_ids=[mirror.id],
                    observed_at=observed, valid_until=expires,
                    ownership=observation.get("ownership"), readiness=observation.get("readiness"),
                    resources=observation.get("resources"), schema=observation.get("schema"))

    def submit(self, **command):
        with self.session_factory() as session:
            row = session.get(RecoveryRow, self.operation_id)
            if (row is None or row.source_id != self.source_id or command.get("kind") != "replacement"
                    or row.journal.get("state") != "submitting" or row.journal.get("submission_command") != command):
                raise MirrorError("MIRROR_CONTROL_CONFLICT", 409)
        return dict(operation_id=self.operation_id, state="accepted", capture_generation=command["capture_generation"],
                    generation_id=command["generation_id"])


def dispatch_recovery(*, settings, session_factory, operation_id, source_id, signals):
    if settings.mirror_recovery_retry_delays_seconds is None:
        raise RuntimeBlocked("recovery_retry_budget_required")
    adapters = compose_mirrors(settings)
    if adapters is None:
        raise RuntimeBlocked("recovery_target_unavailable")
    try:
        runtime = ReplacementDispatch(session_factory=session_factory, operation_id=operation_id,
                                      source_id=source_id, signals=signals)
        recovery = Recovery(session_factory=session_factory, runtime=RuntimeDispatchAdapter(runtime),
                            history=History(session_factory=session_factory, target=adapters.history_target),
                            retry_delays=settings.mirror_recovery_retry_delays_seconds)
        return recovery.dispatch(operation_id=operation_id)
    finally:
        adapters.close()
