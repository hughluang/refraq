"""Offline Metadata seams consumed by Channel authoring and publication."""

from copy import deepcopy

import pytest

from backend.metadata.mirrors import service
from backend.metadata.mirrors.store import MemoryMirrorStore


@pytest.fixture
def registry():
    store = MemoryMirrorStore()
    store.bindings["o1"] = dict(
        source_id="s1", object_id="o1", source_key="sales",
        source_name="Sales", qualified_table="public.orders", table_identity="o1",
    )
    service.bind_management(store=store)
    yield store
    service.bind_management()


def test_preview_resolves_first_object_without_reserving_or_opening(registry):
    before = deepcopy(vars(registry) | {"lock": None})
    first = service.resolve_object_binding("o1")
    second = service.resolve_object_binding("o1")
    assert first == second
    assert first["source_id"] == "s1"
    assert first["object_id"] == "o1"
    assert first["mirror_id"].startswith("mir_")
    assert first["enabled"] is False
    assert first["needs_open"] is True
    assert vars(registry) | {"lock": None} == before
    with registry.transaction() as session:
        result = service.ensure_open_intent(
            session, operation_id="op", channel_id="c", channel_version=1,
            object_ids=["o1"],
        )
    assert result[0]["mirror_id"] == first["mirror_id"]
    assert service.resolve_object_binding("o1")["needs_open"] is False


def test_proof_validator_must_not_return_boolean_success():
    from backend.metadata.mirrors.reads import Reads

    class NeverConnect:
        def begin(self):
            pytest.fail("Unproven release must not reach target")

    reads = Reads(NeverConnect(), authorize_source_read=lambda **kw: None,
                  verify_terminal_proof=lambda **kw: True)
    with pytest.raises(service.MirrorError, match="MIRROR_READ_UNAVAILABLE"):
        reads.release_run_pins(run_id="run", terminal_proof={"terminal": True})


def test_composition_proof_adapter_validates_exact_run_and_rejects_shortcuts():
    from backend.metadata.mirrors.composition import terminal_proof_adapter

    calls = []
    proof = object()

    def validator(**kwargs):
        calls.append(kwargs)
        if kwargs["run_id"] != "terminal-run" or kwargs["terminal_proof"] is not proof:
            raise service.MirrorError("MIRROR_IN_USE", 409)

    check = terminal_proof_adapter(validator)
    check(run_id="terminal-run", terminal_proof=proof)
    assert calls == [dict(run_id="terminal-run", terminal_proof=proof)]
    with pytest.raises(service.MirrorError):
        check(run_id="other-run", terminal_proof=proof)
    with pytest.raises(service.MirrorError):
        check(run_id="terminal-run", terminal_proof=True)
    with pytest.raises(service.MirrorError):
        terminal_proof_adapter(lambda **kwargs: True)(run_id="r", terminal_proof=proof)


def test_same_session_grants_resolver_does_not_open_second_transaction(registry, monkeypatch):
    seen = []

    def authorize(**kwargs):
        seen.append(kwargs)

    service.bind_source_read_authorizer(authorize)
    try:
        with registry.transaction() as session:
            monkeypatch.setattr(registry, "transaction", lambda: pytest.fail("Nested session"))
            bindings = service.authorize_object_reads(
                session=session, execution_user_id="u", object_ids=["o1", "o1"],
            )
        assert seen == [dict(session=registry, execution_user_id="u", source_id="s1")]
        assert bindings[0]["needs_open"] is True
        assert not registry.mirrors
    finally:
        service.bind_source_read_authorizer()


def test_confirmed_publication_revalidates_preview_and_rolls_back(registry):
    preview = service.resolve_object_binding("o1")
    confirmed = [{key: preview[key] for key in ("source_id", "object_id", "mirror_id")}]
    with pytest.raises(service.MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        with registry.transaction() as session:
            service.ensure_open_intent(
                session, operation_id="bad", channel_id="c", channel_version=1,
                object_ids=["o1"], confirmed_mirrors_to_open=[],
            )
    assert not registry.mirrors
    with pytest.raises(RuntimeError):
        with registry.transaction() as session:
            result = service.ensure_open_intent(
                session, operation_id="ok", channel_id="c", channel_version=1,
                object_ids=["o1"], confirmed_mirrors_to_open=confirmed,
            )
            assert result == confirmed
            raise RuntimeError("rollback version and reservation")
    assert not registry.mirrors
    assert not registry.operations
    assert not registry.references
    assert service.resolve_object_binding("o1")["mirror_id"] == preview["mirror_id"]


def test_preview_rejects_unsupported_and_immutable_binding_changes(registry):
    with pytest.raises(service.MirrorError, match="MIRROR_NOT_FOUND"):
        service.resolve_object_binding("missing")
    with registry.transaction() as session:
        service.ensure_open_intent(session, operation_id="op", channel_id="c",
                                   channel_version=1, object_ids=["o1"])
    registry.bindings["o1"]["qualified_table"] = "other.orders"
    with pytest.raises(service.MirrorError, match="MIRROR_CONTROL_CONFLICT"):
        service.resolve_object_binding("o1")


def test_sql_preview_is_read_only_and_uses_supplied_session(monkeypatch):
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session
    from backend.core.time import utc_now
    from backend.metadata.models import CatalogObjectRow, SourceRow
    from backend.metadata.mirrors.models import MirrorRow
    from backend.metadata.mirrors.store import SqlMirrorStore

    engine = create_engine("sqlite://")
    for model in (SourceRow, CatalogObjectRow, MirrorRow):
        model.__table__.create(engine)
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(SourceRow(id="s", key="sales", locator_key="s", name="Sales",
                              kind="database", engine="postgresql", created_at=now, updated_at=now))
        session.add(CatalogObjectRow(id="o", source_id="s", locator_key="o",
                                     object_type="table", schema_name="public", name="orders",
                                     is_present=True, created_at=now, updated_at=now))
    statements = []
    event.listen(engine, "before_cursor_execute",
                 lambda conn, cursor, statement, *args: statements.append(statement))
    store = SqlMirrorStore()
    monkeypatch.setattr(store, "transaction", lambda: pytest.fail("Nested SQL session"))
    service.bind_management(store=store)
    try:
        with Session(engine) as session, session.begin():
            binding = service.resolve_object_binding("o", session=session)
            assert binding["qualified_table"] == "public.orders"
            assert binding["needs_open"] is True
            assert not session.new and not session.dirty
        assert statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
        assert not any("FOR UPDATE" in sql or "advisory" in sql for sql in statements)
    finally:
        service.bind_management()
        engine.dispose()


def test_release_calls_bound_validator_before_target_and_keeps_run_identity():
    from contextlib import contextmanager
    from backend.metadata.mirrors.composition import terminal_proof_adapter
    from backend.metadata.mirrors.reads import Reads

    events = []
    proof = object()

    def validate(**kwargs):
        assert kwargs == dict(run_id="run", terminal_proof=proof)
        events.append("validated")

    class Target:
        @contextmanager
        def begin(self):
            assert events == ["validated"]
            yield self

        def execute(self, statement, parameters):
            assert "release_run_pins" in str(statement)
            assert parameters == {"run": "run"}
            events.append("released")

    reads = Reads(Target(), authorize_source_read=lambda **kw: None,
                  verify_terminal_proof=terminal_proof_adapter(validate))
    reads.release_run_pins(run_id="run", terminal_proof=proof)
    assert events == ["validated", "released"]


def test_direct_mirror_authorization_uses_immutable_source_and_caller_session(registry, monkeypatch):
    with registry.transaction() as session:
        opened = service.ensure_open_intent(session, operation_id="open", channel_id="c",
                                            channel_version=1, object_ids=["o1"])
    mid = opened[0]["mirror_id"]
    seen = []
    service.bind_source_read_authorizer(lambda **kwargs: seen.append(kwargs))
    try:
        with registry.transaction() as session:
            monkeypatch.setattr(registry, "transaction", lambda: pytest.fail("Nested session"))
            bindings = service.authorize_object_reads(
                object_ids=[], mirror_ids=[mid, mid], execution_user_id="u", session=session,
            )
            assert bindings[0]["source_id"] == "s1"
            assert seen == [dict(session=session, execution_user_id="u", source_id="s1")]
            with pytest.raises(service.MirrorError, match="MIRROR_NOT_FOUND"):
                service.authorize_object_reads(object_ids=[], mirror_ids=["unknown"],
                                               execution_user_id="u", session=session)
    finally:
        service.bind_source_read_authorizer()
