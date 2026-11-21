"""Offline Channel mirror integration contracts."""

from types import SimpleNamespace

import pytest

from backend.channel import mirror_reads
from backend.channel.store import ChannelRecord, MemoryChannelStore, empty_graph
from backend.core.time import utc_now


def test_publish_callback_failure_does_not_publish_version():
    store = MemoryChannelStore()
    now = utc_now()
    store.create(ChannelRecord(
        id="chn_one", name="One", description=None, active=False,
        draft_graph=empty_graph(), draft_revision=1, draft_updated_at=now,
        created_at=now, updated_at=now,
    ))
    def reject(session, version, previous):
        assert session is None
        assert version.number == 1
        raise ValueError("intent rejected")
    with pytest.raises(ValueError, match="intent rejected"):
        store.publish_version("chn_one", draft_revision=1, published_at=now,
                              published_by_user_id="usr_one", after=reject)
    assert store.list_versions("chn_one", limit=10, offset=0) == ([], 0)


def test_mirror_node_calls_run_gateway_and_preserves_annotations():
    from backend.channel.nodes.read.mirror import NODE_TYPE

    calls = []
    page = dict(rows=[{"id": 1}], next_key=None, generation_id="gen_one",
                source_ids=["src_one"], freshness="unknown")
    hooks = SimpleNamespace(read_mirror_page=lambda **kw: calls.append(kw) or page)
    result = NODE_TYPE.execute({"config": {"object_id": "obj_one", "freshness_policy": "continue"}}, hooks)
    assert result.status == "succeeded"
    assert result.output == {key: page[key] for key in ("rows", "generation_id", "source_ids", "freshness")}
    assert calls == [dict(object_id="obj_one", after_key=None, limit=500)]


def test_unknown_freshness_does_not_silently_continue_for_fail_policy():
    from backend.channel.nodes.read.mirror import NODE_TYPE

    hooks = SimpleNamespace(read_mirror_page=lambda **kw: dict(
        rows=[{"id": 1}], next_key=None, generation_id="gen_one",
        source_ids=["src_one"], freshness="unknown"))
    result = NODE_TYPE.execute({"config": {"object_id": "obj_one", "freshness_policy": "fail"}}, hooks)
    assert result.status == "failed"


def test_graph_binding_fails_closed_without_gateway(monkeypatch):
    monkeypatch.setattr(mirror_reads, "_reads", None)
    with pytest.raises(mirror_reads.MirrorReadUnavailable):
        mirror_reads.resolve_object("obj_one")


def test_mirror_success_failure_rolls_back_terminal_cas(monkeypatch):
    from contextlib import contextmanager
    from backend.channel import runner

    events = []
    @contextmanager
    def transaction():
        try:
            yield "same_session"
        except ValueError:
            events.append("rollback")
            raise
        events.append("commit")
    monkeypatch.setattr(runner, "session_scope", transaction)
    def succeeded(job_id, **kwargs):
        assert kwargs["session"] == "same_session"
        events.append("cas")
        return SimpleNamespace(status="succeeded")
    monkeypatch.setattr(runner, "mark_succeeded", succeeded)
    def reject(session, run):
        assert session == "same_session"
        events.append("gate")
        raise ValueError("invalid epoch")
    monkeypatch.setattr(runner, "advance_from_run_in_session", reject)
    with pytest.raises(ValueError, match="invalid epoch"):
        runner.complete_mirror_success(SimpleNamespace(job_id="job_one"), {})
    assert events == ["cas", "gate", "rollback"]


def test_sql_publish_callback_shares_version_transaction_and_rolls_back(monkeypatch):
    from contextlib import contextmanager
    from sqlalchemy import create_engine, select
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.orm import Session
    from backend.channel import store as stores
    from backend.channel.models import ChannelRow, ChannelVersionRow

    @compiles(JSONB, "sqlite")
    def jsonb(element, compiler, **kwargs):
        return "JSON"

    engine = create_engine("sqlite://")
    ChannelRow.__table__.create(engine)
    ChannelVersionRow.__table__.create(engine)
    @contextmanager
    def transaction():
        with Session(engine) as session, session.begin():
            yield session
    monkeypatch.setattr(stores, "session_scope", transaction)
    store = stores.SqlChannelStore()
    now = utc_now()
    store.create(ChannelRecord(
        id="chn_one", name="One", description=None, active=False,
        draft_graph=empty_graph(), draft_revision=1, draft_updated_at=now,
        created_at=now, updated_at=now,
    ))
    def reject(session, version, previous):
        assert session.in_transaction()
        assert session.get(ChannelVersionRow, ("chn_one", 1)) is not None
        raise ValueError("intent rejected")
    with pytest.raises(ValueError, match="intent rejected"):
        store.publish_version("chn_one", draft_revision=1, published_at=now,
                              published_by_user_id="usr_one", after=reject)
    with Session(engine) as session:
        assert session.scalars(select(ChannelVersionRow)).all() == []


def test_node_keysets_reuse_gateway_and_skip_only_known_stale():
    from backend.channel.nodes.read.mirror import NODE_TYPE

    calls = []
    def read(**kwargs):
        calls.append(kwargs["after_key"])
        key = kwargs["after_key"]
        return dict(rows=[{"id": 1 if key is None else 2}],
                    next_key=[1] if key is None else None, generation_id="gen_one",
                    source_ids=["src_one"], freshness="ready")
    hooks = SimpleNamespace(read_mirror_page=read)
    result = NODE_TYPE.execute({"config": {"object_id": "obj_one", "freshness_policy": "continue"}}, hooks)
    assert result.output["rows"] == [{"id": 1}, {"id": 2}]
    assert calls == [None, [1]]


def test_catalog_exposes_mirror_once():
    from backend.channel.nodes import list_node_types
    assert [node.type_id for node in list_node_types()].count("read.mirror") == 1


def test_mint_rejects_revoked_identity_before_creating_job(monkeypatch):
    from backend.channel import channel_run
    calls = []
    def reject(*args, **kwargs):
        raise mirror_reads.MirrorDataForbidden()
    monkeypatch.setattr(channel_run, "_preflight_identity", reject)
    monkeypatch.setattr(channel_run, "create_queued_job", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(mirror_reads.MirrorDataForbidden):
        channel_run.mint_followup_run(channel_id="chn_one", channel_name="One",
                                     trigger_kind="retry", trigger_ref="job_old",
                                     trigger_node="nd_trigger", version=1, job_input={})
    assert calls == []
