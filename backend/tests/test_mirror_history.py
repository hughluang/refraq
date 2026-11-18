"""Offline history tests with an in-process SQLite management transaction."""

from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend.metadata.mirrors.history import History
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.service import MirrorError


def point(mid="a", epoch="epoch", seq=0, entry=0):
    return dict(mirror_id=mid, history_epoch=epoch, commit_seq=seq, entry_seq=entry)


class Target:
    def __init__(self):
        self.bounds = {mid: dict(mirror_id=mid, source_id="source", history_epoch="epoch",
                                lower_bound=point(mid), upper_bound=point(mid, seq=2, entry=1))
                       for mid in ("a", "b")}
        self.calls = []
        self.fail = False
        self.applied = {}

    def capture_bound(self, *, mirror_id):
        self.calls.append(mirror_id)
        if self.fail:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
        return deepcopy(self.bounds[mirror_id])

    def read_incremental(self, *, mirror_id, after, through, limit):
        return dict(self.capture_bound(mirror_id=mirror_id), entries=[
            dict(position=point(mirror_id, seq=1, entry=1), origin="live", before=None, after={"secret": "image"})
        ], next_position=through)

    def invalidate(self, *, operation_id, transitions):
        if self.fail:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
        if operation_id not in self.applied:
            for item in transitions:
                mid, epoch = item["mirror_id"], item["history_epoch"]
                self.bounds[mid].update(history_epoch=epoch, lower_bound=point(mid, epoch), upper_bound=point(mid, epoch))
            self.applied[operation_id] = deepcopy(transitions)
        assert self.applied[operation_id] == transitions
        return True


@pytest.fixture
def setup_history():
    engine = create_engine("sqlite://")
    for table in (MirrorRow.__table__, HistoryGateRow.__table__, HistoryInvalidationRow.__table__):
        table.create(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    target = Target()
    auth = {"allowed": True, "calls": []}

    def authorize(**kwargs):
        auth["calls"].append(kwargs)
        if not auth["allowed"]:
            raise MirrorError("AUTH_FORBIDDEN", 403)

    history = History(session_factory=factory, target=target, authorize_source_read=authorize)
    with factory.begin() as session:
        for mid in ("a", "b"):
            session.add(MirrorRow(id=mid, source_id="source", table_identity=mid, enabled=True, state={}))
        session.flush()
        for mid in ("a", "b"):
            history.initialize_gate(session, mirror_id=mid, history_epoch="epoch")
    target.calls.clear()
    return history, factory, target, auth


def proposal(mid="a", epoch="epoch"):
    return dict(mirror_id=mid, history_epoch=epoch, position=point(mid, epoch, 2, 1), source_ids=["source"])


def test_pages_and_final_settlement_reauthorize(setup_history):
    history, factory, target, auth = setup_history
    bound = history.capture_bound(mirror_id="a", execution_user_id="user")
    page = history.read_incremental(mirror_id="a", execution_user_id="user", after=bound["lower_bound"], through=bound["upper_bound"], limit=10)
    assert page["source_ids"] == ["source"]
    assert page["entries"][0]["after"] == {"secret": "image"}
    auth["allowed"] = False
    with factory.begin() as session, pytest.raises(MirrorError) as error:
        history.settlement_guard(session, proposals=[proposal()], execution_user_id="user")
    assert error.value.code == "AUTH_FORBIDDEN"
    with pytest.raises(MirrorError):
        history.read_incremental(mirror_id="a", execution_user_id="user", after=bound["lower_bound"], through=bound["upper_bound"], limit=10)


def test_sorted_locks_same_transaction_and_no_commit(setup_history):
    history, factory, target, auth = setup_history
    locked = []
    with factory() as session:
        @event.listens_for(session, "do_orm_execute")
        def record(state):
            statement = state.statement
            if getattr(statement, "_for_update_arg", None) is not None and "source_mirror_history_gates" in str(statement):
                locked.extend(statement.compile().params.values())
        with session.begin():
            history.settlement_guard(session, proposals=[proposal("b"), proposal("a")], execution_user_id="user")
            assert session.in_transaction()
    assert locked == ["a", "b"]
    assert target.calls == ["a", "b"]


@pytest.mark.parametrize("failure", ["epoch", "lower", "unavailable", "provenance"])
def test_settlement_fails_closed(setup_history, failure):
    history, factory, target, auth = setup_history
    p = proposal()
    if failure == "epoch":
        target.bounds["a"]["history_epoch"] = "other"
    elif failure == "lower":
        target.bounds["a"]["lower_bound"] = point(seq=1, entry=1)
    elif failure == "unavailable":
        target.fail = True
    else:
        p["source_ids"] = []
    with pytest.raises(MirrorError), factory.begin() as session:
        history.settlement_guard(session, proposals=[p], execution_user_id="user")


def test_invalidation_rollback_never_touches_target(setup_history):
    history, factory, target, auth = setup_history
    with pytest.raises(RuntimeError), factory.begin() as session:
        history.invalidate_history(session, mirror_ids=["b", "a"], reason="retention", operation_id="operation")
        assert not target.applied
        raise RuntimeError("caller rollback")
    with factory() as session:
        assert session.get(HistoryInvalidationRow, "operation") is None
        assert session.get(HistoryGateRow, "a").status == "available"


def test_outbox_failure_closed_and_replay_after_target_commit(setup_history):
    history, factory, target, auth = setup_history
    with factory.begin() as session:
        changes = history.invalidate_history(session, mirror_ids=["b", "a"], reason="retention", operation_id="operation")
    assert [item["mirror_id"] for item in changes] == ["a", "b"]
    with pytest.raises(MirrorError):
        history.capture_bound(mirror_id="a", execution_user_id="user")
    target.fail = True
    with pytest.raises(MirrorError):
        history.consume_invalidation(operation_id="operation")
    target.fail = False
    # Simulate a target commit followed by a lost response/management rollback.
    target.invalidate(operation_id="operation", transitions=changes)
    history.consume_invalidation(operation_id="operation")
    history.consume_invalidation(operation_id="operation")
    with factory.begin() as session:
        assert session.get(HistoryInvalidationRow, "operation").status == "applied"
        assert session.get(HistoryGateRow, "a").status == "available"
        assert history.invalidate_history(session, mirror_ids=["a", "b"], reason="retention", operation_id="operation") == changes
    with pytest.raises(MirrorError), factory.begin() as session:
        history.settlement_guard(session, proposals=[proposal()], execution_user_id="user")


def test_target_sql_uses_live_prefix_and_restricted_bootstrap():
    root = Path(__file__).parents[1] / "metadata" / "mirrors"
    sql = (root / "history.sql").read_text()
    assert "FOR SHARE" in sql
    assert "FROM source_mirror_state.live_log" in sql
    assert "ORDER BY value->>'mirror_id'" in sql
    assert "DELETE FROM source_mirror_state.live_log" in sql
    assert "SECURITY DEFINER SET search_path = pg_catalog, source_mirror_state" in sql
    assert "nextval" not in sql
    from backend.metadata.mirrors.bootstrap import FUNCTIONS
    assert FUNCTIONS["history_bound(text)"] == "refraq_mirror_gateway"
    assert FUNCTIONS["invalidate_history(text,jsonb)"] == "refraq_mirror_applier"
