"""Authorized committed history and management-transaction settlement gates."""

import json
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.metadata.mirrors.authorization import authorize_source_data
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.service import MirrorError

__all__ = ["History", "SqlHistoryTarget", "bind_history", "capture_bound",
           "read_incremental", "settlement_guard", "invalidate_history"]


def _invalid():
    raise MirrorError("MIRROR_HISTORY_INVALID", 409)


def _position(value, mirror_id, epoch):
    if not isinstance(value, dict) or value.get("mirror_id") != mirror_id or value.get("history_epoch") != epoch:
        _invalid()
    pair = (value.get("commit_seq"), value.get("entry_seq"))
    if any(type(n) is not int or n < 0 for n in pair):
        _invalid()
    return pair


def _point(mirror_id, epoch, pair):
    return dict(mirror_id=mirror_id, history_epoch=epoch, commit_seq=pair[0], entry_seq=pair[1])


def _validated_bounds(bound, *, mirror_id, source_id, history_epoch):
    if (not isinstance(bound, dict) or bound.get("source_id") != source_id
            or bound.get("history_epoch") != history_epoch):
        _invalid()
    lower = _position(bound.get("lower_bound"), mirror_id, history_epoch)
    upper = _position(bound.get("upper_bound"), mirror_id, history_epoch)
    if upper < lower:
        _invalid()
    return lower, upper


def admit_observed_history(session, *, mirror, gate, history_epoch, bound):
    """Admit validated bounds while the caller holds the mirror and any existing gate lock."""
    lower, upper = _validated_bounds(bound, mirror_id=mirror.id, source_id=mirror.source_id,
                                     history_epoch=history_epoch)
    if gate is None:
        session.add(HistoryGateRow(mirror_id=mirror.id, history_epoch=history_epoch,
                                   lower_commit_seq=lower[0], lower_entry_seq=lower[1], status="available"))
    elif (gate.status != "available" or gate.history_epoch != history_epoch
          or (gate.lower_commit_seq, gate.lower_entry_seq) != lower):
        _invalid()
    return _point(mirror.id, history_epoch, lower), _point(mirror.id, history_epoch, upper)


class SqlHistoryTarget:
    """Restricted gateway reads; invalidation uses the separate applier identity."""

    def __init__(self, *, engine, invalidation_engine, timeout_ms):
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise ValueError("A positive bounded target timeout is required")
        self.engine = engine
        self.invalidation_engine = invalidation_engine
        self.timeout_ms = timeout_ms

    def validate(self):
        if self._call("SELECT source_mirror_state.history_version()", {}) != 1:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)

    def _call(self, function, parameters, *, mutation=False):
        try:
            with (self.invalidation_engine if mutation else self.engine).begin() as connection:
                connection.execute(text("SELECT set_config('statement_timeout', :timeout, true), "
                                        "set_config('lock_timeout', :timeout, true)"),
                                   {"timeout": str(self.timeout_ms)})
                return connection.execute(text(function), parameters).scalar_one()
        except SQLAlchemyError as exc:
            # Never propagate driver details, parameters, keys or row images.
            code = "MIRROR_HISTORY_INVALID" if "MIRROR_HISTORY_INVALID" in str(getattr(exc, "orig", "")) else "MIRROR_READ_UNAVAILABLE"
            raise MirrorError(code, 409 if code == "MIRROR_HISTORY_INVALID" else 503) from None

    def capture_bound(self, *, mirror_id):
        return self._call("SELECT source_mirror_state.history_bound(:mirror)", {"mirror": mirror_id})

    def read_incremental(self, *, mirror_id, after, through, limit):
        return self._call(
            "SELECT source_mirror_state.history_page(:mirror, CAST(:after AS jsonb), CAST(:through AS jsonb), :limit)",
            {"mirror": mirror_id, "after": json.dumps(after), "through": json.dumps(through), "limit": limit})

    def invalidate(self, *, operation_id, transitions):
        return self._call(
            "SELECT source_mirror_state.invalidate_history(:operation, CAST(:transitions AS jsonb))",
            {"operation": operation_id, "transitions": json.dumps(transitions)}, mutation=True)


class History:
    def __init__(self, *, session_factory, target, authorize_source_read=authorize_source_data):
        if target is None or not callable(authorize_source_read):
            raise ValueError("Target validation and current Source authorization are required")
        self.session_factory = session_factory
        self.target = target
        self.authorize_source_read = authorize_source_read

    def _gate(self, session, mirror_id, *, admit=False):
        gate = session.execute(select(HistoryGateRow).where(
            HistoryGateRow.mirror_id == mirror_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
        if gate is None:
            if not admit:
                _invalid()
            mirror = session.execute(select(MirrorRow).where(
                MirrorRow.id == mirror_id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
            if mirror is None or not (mirror.state or {}).get("history_epoch"):
                _invalid()
            self.initialize_gate(session, mirror_id=mirror_id,
                                 history_epoch=mirror.state["history_epoch"])
            gate = session.get(HistoryGateRow, mirror_id)
        return gate

    def _authorize(self, session, mirror_id, execution_user_id):
        mirror = session.get(MirrorRow, mirror_id, populate_existing=True)
        if mirror is None:
            raise MirrorError("MIRROR_NOT_FOUND", 404)
        self.authorize_source_read(session=session, execution_user_id=execution_user_id,
                                   source_id=mirror.source_id)
        return mirror.source_id

    def _bounds(self, gate, bound, source_id):
        if gate.status != "available":
            _invalid()
        lower, upper = _validated_bounds(bound, mirror_id=gate.mirror_id, source_id=source_id,
                                         history_epoch=gate.history_epoch)
        if lower != (gate.lower_commit_seq, gate.lower_entry_seq):
            _invalid()
        return lower, upper

    def initialize_gate(self, session, *, mirror_id, history_epoch):
        """Admission only: serialize against the immutable management mirror binding."""
        mirror = session.execute(select(MirrorRow).where(MirrorRow.id == mirror_id).with_for_update()).scalar_one()
        existing = session.get(HistoryGateRow, mirror_id)
        if existing is not None:
            if existing.history_epoch != history_epoch:
                _invalid()
            return
        bound = self.target.capture_bound(mirror_id=mirror_id)
        admit_observed_history(session, mirror=mirror, gate=None, history_epoch=history_epoch, bound=bound)
        session.flush()

    def capture_bound(self, *, mirror_id, execution_user_id):
        with self.session_factory() as session, session.begin():
            source = self._authorize(session, mirror_id, execution_user_id)
            gate = self._gate(session, mirror_id, admit=True)
            bound = self.target.capture_bound(mirror_id=mirror_id)
            self._bounds(gate, bound, source)
            return bound

    def read_incremental(self, *, mirror_id, execution_user_id, after, through, limit):
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("History page limit must be between 1 and 500")
        with self.session_factory() as session, session.begin():
            gate = self._gate(session, mirror_id)
            source = self._authorize(session, mirror_id, execution_user_id)
            result = self.target.read_incremental(mirror_id=mirror_id, after=after, through=through, limit=limit)
            lower, upper = self._bounds(gate, result, source)
            start = _position(after, mirror_id, gate.history_epoch)
            end = _position(through, mirror_id, gate.history_epoch)
            next_pair = _position(result["next_position"], mirror_id, gate.history_epoch)
            if not lower <= start <= next_pair <= end <= upper:
                _invalid()
            previous = start
            entries = result["entries"]
            if len(entries) > limit:
                _invalid()
            projected = []
            for entry in entries:
                current = _position(entry["position"], mirror_id, gate.history_epoch)
                if not previous < current <= next_pair or entry.get("origin") != "live":
                    _invalid()
                previous = current
                before, after_image = entry["before"], entry["after"]
                if before is None and after_image is None:
                    _invalid()
                operation = "insert" if before is None else "delete" if after_image is None else "update"
                projected.append({**entry, "operation": operation})
            return {**result, "entries": projected, "source_ids": [source]}

    def settlement_guard(self, session, *, proposals, execution_user_id):
        """Validate without commit; caller must update checkpoints in THIS transaction."""
        if not session.in_transaction():
            raise ValueError("Settlement requires an active caller management transaction")
        proposals = list(proposals)
        ids = sorted({proposal["mirror_id"] for proposal in proposals})
        gates = {mirror_id: self._gate(session, mirror_id) for mirror_id in ids}
        for mirror_id in ids:
            gate = gates[mirror_id]
            source = self._authorize(session, mirror_id, execution_user_id)
            bound = self.target.capture_bound(mirror_id=mirror_id)
            lower, upper = self._bounds(gate, bound, source)
            for proposal in proposals:
                if proposal["mirror_id"] != mirror_id:
                    continue
                position = _position(proposal["position"], mirror_id, gate.history_epoch)
                if proposal.get("history_epoch") != gate.history_epoch or proposal.get("source_ids") != [source] or not lower <= position <= upper:
                    _invalid()

    def invalidate_history(self, session, *, mirror_ids, reason, operation_id):
        if not session.in_transaction():
            raise ValueError("Invalidation requires an active caller transaction")
        ids = sorted(set(mirror_ids))
        if not ids or not reason or len(reason) > 64 or not operation_id or len(operation_id) > 64:
            raise ValueError("Bounded invalidation identity and reason are required")
        gates = [self._gate(session, mirror_id) for mirror_id in ids]
        receipt = session.get(HistoryInvalidationRow, operation_id)
        if receipt is not None:
            if [item["mirror_id"] for item in receipt.transitions] != ids or receipt.reason != reason:
                _invalid()
            return receipt.transitions
        if any(gate.status != "available" for gate in gates):
            _invalid()
        transitions = []
        for gate in gates:
            old_epoch = gate.history_epoch
            gate.history_epoch = uuid4().hex
            gate.lower_commit_seq = gate.lower_entry_seq = 0
            gate.status = "invalidating"
            transitions.append(dict(mirror_id=gate.mirror_id, old_epoch=old_epoch, history_epoch=gate.history_epoch))
        session.add(HistoryInvalidationRow(operation_id=operation_id, reason=reason,
                                          transitions=transitions, status="pending"))
        session.flush()
        return transitions

    def consume_invalidation(self, *, operation_id):
        """Use an independent session so uncommitted invalidation cannot be consumed."""
        with self.session_factory() as session, session.begin():
            self._consume_invalidation(session, operation_id=operation_id)

    def _consume_invalidation(self, session, *, operation_id):
        receipt = session.get(HistoryInvalidationRow, operation_id)
        if receipt is None:
            raise ValueError("Unknown invalidation operation")
        gates = [self._gate(session, item["mirror_id"]) for item in receipt.transitions]
        receipt = session.execute(select(HistoryInvalidationRow).where(
            HistoryInvalidationRow.operation_id == operation_id).with_for_update().execution_options(populate_existing=True)).scalar_one()
        if receipt.status == "applied":
            return
        for gate, transition in zip(gates, receipt.transitions):
            if gate.history_epoch != transition["history_epoch"] or gate.status != "invalidating":
                _invalid()
        if self.target.invalidate(operation_id=operation_id, transitions=receipt.transitions) is not True:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
        for gate in gates:
            gate.status = "available"
        receipt.status = "applied"
        session.flush()


_history = None


def bind_history(*, session_factory, target):
    global _history
    _history = History(session_factory=session_factory, target=target)


def _service():
    if _history is None:
        raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
    return _history


def capture_bound(*, mirror_id, execution_user_id):
    return _service().capture_bound(mirror_id=mirror_id, execution_user_id=execution_user_id)


def read_incremental(*, mirror_id, execution_user_id, after, through, limit):
    return _service().read_incremental(mirror_id=mirror_id, execution_user_id=execution_user_id, after=after, through=through, limit=limit)


def settlement_guard(session, *, proposals, execution_user_id):
    return _service().settlement_guard(session, proposals=proposals, execution_user_id=execution_user_id)


def invalidate_history(session, *, mirror_ids, reason, operation_id):
    return _service().invalidate_history(session, mirror_ids=mirror_ids, reason=reason, operation_id=operation_id)
