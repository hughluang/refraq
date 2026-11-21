"""Offline history tests with an in-process SQLite management transaction."""

from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.metadata.mirrors import history as history_api
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
        self.entries = {mid: [dict(
            position=point(mid, seq=1, entry=1), origin="live", operation="upsert",
            source_id="source", generation_id="generation", capture_generation="capture",
            typed_key={"id": 7}, before=None, after={"secret": "image"},
        )] for mid in self.bounds}

    def capture_bound(self, *, mirror_id):
        self.calls.append(mirror_id)
        if self.fail:
            raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)
        return deepcopy(self.bounds[mirror_id])

    def read_incremental(self, *, mirror_id, after, through, limit):
        def cursor(position):
            return position["commit_seq"], position["entry_seq"]

        entries = [entry for entry in self.entries[mirror_id]
                   if cursor(after) < cursor(entry["position"]) <= cursor(through)][:limit]
        next_position = entries[-1]["position"] if len(entries) == limit else through
        return dict(self.capture_bound(mirror_id=mirror_id), entries=deepcopy(entries), next_position=next_position)

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


@pytest.mark.parametrize("metadata_epoch", ["epoch", None, "different"])
def test_bound_api_admits_missing_gate_only_with_metadata_target_agreement(setup_history, monkeypatch, metadata_epoch):
    history, factory, target, auth = setup_history
    monkeypatch.setattr(history_api, "_history", history)
    with factory.begin() as session:
        session.delete(session.get(HistoryGateRow, "a"))
        session.get(MirrorRow, "a").state = {"history_epoch": metadata_epoch}
    if metadata_epoch != "epoch":
        with pytest.raises(MirrorError):
            history_api.capture_bound(mirror_id="a", execution_user_id="user")
        with factory() as session:
            assert session.get(HistoryGateRow, "a") is None
    else:
        bound = history_api.capture_bound(mirror_id="a", execution_user_id="user")
        page = history_api.read_incremental(mirror_id="a", execution_user_id="user",
                                           after=bound["lower_bound"], through=bound["upper_bound"], limit=10)
        assert page["source_ids"] == ["source"]
        with factory() as session:
            assert session.get(HistoryGateRow, "a").history_epoch == "epoch"


def test_pages_reauthorize(setup_history):
    history, factory, target, auth = setup_history
    bound = history.capture_bound(mirror_id="a", execution_user_id="user")
    page = history.read_incremental(mirror_id="a", execution_user_id="user", after=bound["lower_bound"], through=bound["upper_bound"], limit=10)
    assert auth["calls"][0]["execution_user_id"] == "user"
    assert auth["calls"][0]["session"].bind is factory.kw["bind"]
    assert page["source_ids"] == ["source"]
    assert page["entries"][0]["after"] == {"secret": "image"}
    auth["allowed"] = False
    with pytest.raises(MirrorError) as error:
        history.read_incremental(mirror_id="a", execution_user_id="user", after=bound["lower_bound"], through=bound["upper_bound"], limit=10)
    assert error.value.code == "AUTH_FORBIDDEN"


@pytest.mark.parametrize("writer_verb,before,after,operation", [
    ("upsert", None, {"tenant": "x", "id": 7, "value": None}, "insert"),
    ("upsert", {"tenant": "x", "id": 7, "value": None}, {"tenant": "x", "id": 7, "value": "new"}, "update"),
    ("delete", {"tenant": "x", "id": 7, "value": "old"}, None, "delete"),
])
def test_authorized_history_projects_effective_writer_operation(setup_history, writer_verb, before, after, operation):
    history, _, target, _ = setup_history
    stored = target.entries["a"][0]
    stored.update(operation=writer_verb, before=before, after=after, typed_key={"tenant": "x", "id": 7})
    bound = history.capture_bound(mirror_id="a", execution_user_id="user")

    page = history.read_incremental(mirror_id="a", execution_user_id="user",
                                    after=bound["lower_bound"], through=bound["upper_bound"], limit=1)

    assert page["entries"] == [dict(stored, operation=operation)]
    assert page["next_position"] == stored["position"]
    assert stored["operation"] == writer_verb


def test_authorized_history_rejects_entry_with_no_images(setup_history):
    history, _, target, _ = setup_history
    target.entries["a"][0].update(operation="delete", before=None, after=None)
    bound = history.capture_bound(mirror_id="a", execution_user_id="user")

    with pytest.raises(MirrorError) as error:
        history.read_incremental(mirror_id="a", execution_user_id="user",
                                 after=bound["lower_bound"], through=bound["upper_bound"], limit=10)

    assert error.value.code == "MIRROR_HISTORY_INVALID"


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
    with pytest.raises(MirrorError) as error:
        history.read_incremental(
            mirror_id="a", execution_user_id="user",
            after=point(), through=point(seq=3, entry=1), limit=10,
        )
    assert error.value.code == "MIRROR_HISTORY_INVALID"


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
