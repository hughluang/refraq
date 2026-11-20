"""Native gates for the durable open operation and isolated target bootstrap."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import os
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.errors import AppError
from backend.core.time import utc_now
from backend.metadata.capture.store import load_binding, save_binding
from backend.metadata.models import CatalogObjectRow, SourceCaptureBindingRow, SourceRow
from backend.metadata.mirrors import service
from backend.metadata.mirrors.bootstrap import create_generation, install
from backend.metadata.mirrors.history import History
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import (
    MirrorIntentReceiptRow, MirrorOperationRow, MirrorPublicationRow, MirrorReferenceRow, MirrorRow,
)
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.schemas import Mirror
from backend.metadata.mirrors.store import SqlMirrorStore
from backend.metadata.mirrors.types import AnchoredProfile, Authority, PartitionIdentity


@pytest.fixture(scope="module")
def target_dsn():
    dsn = os.getenv("REFRAQ_MIRROR_ALLOCATION_TEST_DSN")
    if not dsn:
        pytest.skip("Set REFRAQ_MIRROR_ALLOCATION_TEST_DSN to a disposable PostgreSQL target")
    with psycopg.connect(dsn, autocommit=True) as connection:
        install(connection)
    return dsn


@pytest.fixture
def opened(target_dsn, monkeypatch):
    database = "management_" + uuid4().hex
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(target_dsn, dbname=database))
    try:
        for model in (SourceRow, CatalogObjectRow, SourceCaptureBindingRow, MirrorRow,
                      MirrorOperationRow, MirrorPublicationRow, MirrorReferenceRow,
                      MirrorIntentReceiptRow, HistoryGateRow, HistoryInvalidationRow, RecoveryRow):
            model.__table__.create(engine)
        store = SqlMirrorStore()
        store.transaction = sessionmaker(engine).begin
        monkeypatch.setattr(service, "_store", store)
        source_id = uuid4().hex
        authority = Authority(source_id, "binding_" + source_id, 3, "owner", 4, 2, "1")
        instant = utc_now()
        with store.transaction() as session:
            session.add(SourceRow(id=source_id, key="orders", locator_key="orders", name="Orders",
                                  kind="database", engine="postgresql", capture_revision=2,
                                  capture_credential_ciphertext="fixture", created_at=instant, updated_at=instant))
            session.add(CatalogObjectRow(id="orders", source_id=source_id, locator_key="orders",
                                         object_type="table", schema_name="sales", name="orders",
                                         created_at=instant, updated_at=instant))
        with store.transaction() as session:
            preview, = service.resolve_object_bindings(object_ids=["orders"], session=session)
            confirmed = {key: preview[key] for key in ("source_id", "object_id", "mirror_id")}
            service.ensure_open_intent(session, operation_id="publish", channel_id="channel", channel_version=1,
                                       object_ids=["orders"], confirmed_mirrors_to_open=[confirmed])
            mirror_id = confirmed["mirror_id"]
            operation, = store.ops(session, mirror_id)
        prepare_fence(target_dsn, mirror_id, authority)
        with store.transaction() as session:
            state = asdict(authority)
            state["binding_id"] = state.pop("resource_binding_id")
            save_binding(session, dict(state, capture_generation=1, desired="configured",
                                       published_scope=service.read_published_scope(session, source_id)))
        yield store, mirror_id, operation["id"], authority
    finally:
        engine.dispose()
        with psycopg.connect(target_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def target_request(authority):
    return dict(authority=authority, table_identity="orders", history_epoch="epoch", schema_fingerprint="schema",
                columns={"tenant": "text", "id": "bigint", "amount": "numeric(8,2)", "seen": "timestamptz"},
                key_columns=("tenant", "id"), partition_identity=PartitionIdentity("cluster", "incarnation", 0),
                start_offset=-1)


def prepare_fence(dsn, mirror_id, authority):
    with psycopg.connect(dsn) as connection:
        connection.execute("SET LOCAL ROLE refraq_mirror_owner")
        connection.execute(
            "INSERT INTO source_mirror_state.mirrors (id, source_id, table_identity, authority, history_epoch) "
            "VALUES (%s, %s, 'orders', %s, 'epoch')", (mirror_id, authority.source_id, Jsonb(asdict(authority))),
        )


def assert_unavailable(dsn, mirror_id):
    with psycopg.connect(dsn, autocommit=True) as connection:
        row = connection.execute("SELECT published_generation_id FROM source_mirror_state.mirrors WHERE id = %s",
                                 (mirror_id,)).fetchone()
        assert row is None or row == (None,)
        connection.execute("SET ROLE refraq_mirror_gateway")
        with pytest.raises(psycopg.Error, match="MIRROR_READ_UNAVAILABLE"):
            connection.execute("SELECT source_mirror_state.acquire_pin('run', %s)", (mirror_id,))


@pytest.mark.integration
def test_native_first_assignment_requires_exact_prepared_fence(target_dsn):
    authority = Authority(uuid4().hex, "binding", 1, "first-owner", 4, 2, "1")
    mirror_id = "mir_" + uuid4().hex
    request = dict(target_request(authority), mirror_id=mirror_id, generation_id=uuid4().hex,
                   operation_id=uuid4().hex, require_prepared_fence=True)
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        with pytest.raises(ValueError, match="fence"):
            create_generation(connection, **request)
        assert connection.execute("SELECT id FROM source_mirror_state.mirrors WHERE id = %s",
                                  (mirror_id,)).fetchone() is None
        prepare_fence(target_dsn, mirror_id, authority)
        assert_unavailable(target_dsn, mirror_id)
        assert connection.execute("SELECT id FROM source_mirror_state.generations WHERE mirror_id = %s",
                                  (mirror_id,)).fetchone() is None
        with pytest.raises(ValueError, match="fence"):
            create_generation(connection, **(request | {"authority": replace(authority, control_revision=3)}))
        with pytest.raises(ValueError, match="fence"):
            create_generation(connection, **(request | {"history_epoch": "stale"}))
        with connection.transaction():
            with pytest.raises(ValueError, match="transaction"):
                create_generation(connection, **request)
        assert create_generation(connection, **request) == request["generation_id"]
        assert create_generation(connection, **request) == request["generation_id"]
    assert_unavailable(target_dsn, mirror_id)


@pytest.mark.integration
def test_native_exact_bootstrap_retry_and_conflicting_facts(target_dsn):
    authority = Authority(uuid4().hex, "binding", 3, "owner", 4, 2, "capture")
    mirror_id, generation_id, operation_id = "mir_" + uuid4().hex, uuid4().hex, uuid4().hex
    request = dict(target_request(authority), mirror_id=mirror_id, generation_id=generation_id,
                   operation_id=operation_id)
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        create_generation(connection, **request)
        assert create_generation(connection, **request) == generation_id
        conflicts = (
            {"authority": replace(authority, owner_epoch=4)},
            {"authority": replace(authority, capture_generation="other")},
            {"table_identity": "other"}, {"mirror_id": "mir_" + uuid4().hex},
            {"history_epoch": "other"}, {"start_offset": 0},
            {"operation_id": uuid4().hex}, {"generation_id": uuid4().hex},
            {"schema_fingerprint": "other"}, {"columns": {**request["columns"], "amount": "numeric(8,3)"}},
            {"columns": dict(reversed(list(request["columns"].items())))},
            {"key_columns": ("id", "tenant")},
            {"partition_identity": PartitionIdentity("cluster", "replacement", 0)},
        )
        for conflict in conflicts:
            with pytest.raises(ValueError, match="binding|authority"):
                create_generation(connection, **(request | conflict))
        assert connection.execute(
            "SELECT count(*) FROM source_mirror_state.generations WHERE mirror_id = %s", (mirror_id,)
        ).fetchone() == (1,)
        table, = connection.execute(
            "SELECT table_name FROM source_mirror_state.generations WHERE id = %s", (generation_id,),
        ).fetchone()
        assert connection.execute(sql.SQL("SELECT count(*) FROM source_mirror.{}").format(
            sql.Identifier(table))).fetchone() == (0,)
        connection.execute("SET ROLE refraq_mirror_applier")
        metadata, = connection.execute("SELECT source_mirror_state.delivery_metadata(%s)", (generation_id,)).fetchone()
        assert metadata == dict(generation_id=generation_id, authority=asdict(authority), table_identity="orders",
                                mirror_id=mirror_id, operation_id=request["operation_id"], history_epoch="epoch",
                                fence_receipt=None, start_offset=request["start_offset"],
                                capture_generation="capture", schema_fingerprint="schema", key_columns=["tenant", "id"],
                                column_names=list(request["columns"]), native_types={**request["columns"],
                                "seen": "timestamp with time zone"}, partition_identity=asdict(request["partition_identity"]),
                                cleanup_pending=False, status="building")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(sql.SQL("SELECT * FROM source_mirror.{}").format(sql.Identifier(table)))
    assert_unavailable(target_dsn, mirror_id)


@pytest.mark.integration
def test_native_anchored_allocation_pins_the_fresh_profile_on_retry(target_dsn):
    authority = Authority(uuid4().hex, "binding", 3, "owner", 4, 2, "capture")
    profile = AnchoredProfile(4)
    request = dict(target_request(authority), mirror_id="mir_" + uuid4().hex, generation_id=uuid4().hex,
                   operation_id=uuid4().hex, anchored_profile=profile)
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        with pytest.raises(ValueError, match="fresh log origin"):
            create_generation(connection, **(request | {"start_offset": 0}))
        generation_id = create_generation(connection, **request)
        assert create_generation(connection, **request) == generation_id
        for changed in (None, AnchoredProfile(5)):
            with pytest.raises(ValueError, match="binding mismatch"):
                create_generation(connection, **(request | {"anchored_profile": changed}))
        connection.execute("SET ROLE refraq_mirror_applier")
        metadata, = connection.execute("SELECT source_mirror_state.delivery_metadata(%s)", (generation_id,)).fetchone()
        assert metadata["anchored_profile"] == asdict(profile)
        assert metadata["anchored_coverage"] is metadata["anchored_seal"] is None
        progress, = connection.execute(
            "SELECT source_mirror_state.apply_batch(%s, %s, %s, '[]'::jsonb, %s, NULL::jsonb)",
            (Jsonb(asdict(authority)), generation_id, Jsonb(asdict(request["partition_identity"])), Jsonb(asdict(profile))),
        ).fetchone()
        assert progress == {"offset": -1, "commit_seq": 0}


@pytest.mark.integration
def test_native_recovery_rejects_drift_matching_a_changed_request(target_dsn):
    authority = Authority(uuid4().hex, "binding", 3, "owner", 4, 2, "capture")
    request = dict(target_request(authority), mirror_id="mir_" + uuid4().hex, generation_id=uuid4().hex,
                   operation_id=uuid4().hex)
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        generation_id = create_generation(connection, **request)
        table, = connection.execute(
            "SELECT table_name FROM source_mirror_state.generations WHERE id = %s", (generation_id,),
        ).fetchone()
        connection.execute("UPDATE source_mirror_state.generations SET applied_offset = 0 WHERE id = %s",
                           (generation_id,))
        assert create_generation(connection, **request) == generation_id
        with pytest.raises(ValueError, match="binding"):
            create_generation(connection, **(request | {"start_offset": 0}))
        connection.execute(sql.SQL("ALTER TABLE source_mirror.{} ALTER COLUMN amount TYPE numeric(8,3)").format(
            sql.Identifier(table)))
        with pytest.raises(ValueError, match="binding"):
            create_generation(connection, **request)
        with pytest.raises(ValueError, match="binding"):
            create_generation(connection, **(request | {"columns": {**request["columns"], "amount": "numeric(8,3)"}}))


@pytest.mark.integration
def test_native_bootstrap_rejects_stale_history_epoch(target_dsn):
    authority = Authority(uuid4().hex, "binding", 3, "owner", 4, 2, "capture")
    request = dict(target_request(authority), mirror_id="mir_" + uuid4().hex, generation_id=uuid4().hex,
                   operation_id=uuid4().hex)
    with psycopg.connect(target_dsn, autocommit=True) as connection:
        assert create_generation(connection, **request) == request["generation_id"]
        transition = dict(mirror_id=request["mirror_id"], old_epoch=request["history_epoch"], history_epoch="new-epoch")
        assert connection.execute("SELECT source_mirror_state.invalidate_history(%s, %s)",
                                  (uuid4().hex, Jsonb([transition]))).fetchone() == (True,)
        with pytest.raises(ValueError, match="binding|fence"):
            create_generation(connection, **request)
        replacement = dict(request, generation_id=uuid4().hex, operation_id=uuid4().hex)
        with pytest.raises(ValueError, match="binding|fence"):
            create_generation(connection, **replacement)
        assert create_generation(connection, **dict(replacement, history_epoch="new-epoch")) == replacement["generation_id"]


def reconcile(opened, allocate, *, verifier=lambda **_: True, **changes):
    _, mirror_id, operation_id, authority = opened
    binding = dict(target_request(authority), object_id="orders", qualified_table="sales.orders") | changes
    return service.reconcile_open_generation(mirror_id=mirror_id, operation_id=operation_id,
                                             binding=service.OpenGenerationBinding(**binding),
                                             verify_binding=verifier, allocate=allocate)


@pytest.mark.integration
def test_replacement_only_allocates_the_audited_generation(opened):
    store, mirror_id, initial_operation_id, authority = opened
    recovery_id, generation_id, identity = 'mrec_fixture', uuid4().hex, uuid4().hex
    submission = dict(operation_id=recovery_id, mirror_id=mirror_id, capture_generation=authority.capture_generation,
                      generation_id=generation_id, history_epoch='epoch')
    with store.transaction() as session:
        state = load_binding(session, authority.source_id)
        scope = state['published_scope']
        state['allocation'] = dict(command=dict(kind='replace_owner', operation_id=recovery_id, replacement=dict(
            scope=dict(submission=submission, recovery_request_identity=identity))))
        save_binding(session, state)
        session.add(HistoryGateRow(mirror_id=mirror_id, history_epoch='epoch', status='available',
                                   lower_commit_seq=0, lower_entry_seq=0))
        session.add(RecoveryRow(operation_id=recovery_id, source_id=authority.source_id, mirror_id=mirror_id,
                                identity=identity, journal=dict(state='dispatched', submission_command=submission)))
        initial, = store.ops(session, mirror_id)
        store.save_op(session, dict(initial, state='applied', publication_receipt={'initial': True}))
    pending, applied = service.current_open_preparations(
        authority=authority, published_scope=scope, observe_committed=lambda **_: pytest.fail('observed initial open'),
    )
    replacement, = pending
    assert replacement['operation_id'] == recovery_id
    assert applied == []

    def allocate(**request):
        assert request['generation_id'] == generation_id
        assert request['operation_id'] == recovery_id
        return generation_id

    replacement_open = (store, mirror_id, recovery_id, authority)
    assert reconcile(replacement_open, allocate) == generation_id
    assert reconcile(replacement_open, lambda **_: pytest.fail('allocated twice')) == generation_id
    with store.transaction() as session:
        service.require_current_open_allocations(session, authority=authority, allocations=[(replacement, generation_id)])
        recovery = session.get(RecoveryRow, recovery_id)
        recovery.journal = dict(recovery.journal, submission_command=dict(submission, generation_id='superseded'))
    with store.transaction() as session, pytest.raises(AppError, match='MIRROR_CONTROL_CONFLICT'):
        service.require_current_open_allocations(session, authority=authority, allocations=[(replacement, generation_id)])
    assert initial_operation_id != recovery_id


@pytest.mark.integration
def test_native_concurrent_claims_and_lost_allocation_response(opened, target_dsn):
    store, mirror_id, operation_id, _ = opened
    before = service.get_mirror(mirror_id)
    barrier = Barrier(2, timeout=10)
    dispatched = []

    def allocate(*, lose, **request):
        assert request["require_prepared_fence"] is True
        with store.transaction() as session:
            claimed, = store.ops(session, mirror_id)
            assert claimed["id"] == operation_id and claimed["state"] == "pending"
            assert claimed["allocation"]["generation_id"] == request["generation_id"]
            assert claimed["allocation"]["mirror_revision"] == before["control"]["control_revision"]
            assert not claimed["allocation"]["observed"]
        assert_unavailable(target_dsn, mirror_id)
        dispatched.append(request["generation_id"])
        barrier.wait()
        with psycopg.connect(target_dsn, autocommit=True) as connection:
            generation_id = create_generation(connection, **request)
        if lose:
            raise TimeoutError("committed response lost")
        return generation_id

    with ThreadPoolExecutor(2) as workers:
        first = workers.submit(reconcile, opened, lambda **request: allocate(lose=True, **request))
        second = workers.submit(reconcile, opened, lambda **request: allocate(lose=True, **request))
        for task in (first, second):
            with pytest.raises(TimeoutError, match="response lost"):
                task.result(timeout=20)
    with store.transaction() as session:
        claimed, = store.ops(session, mirror_id)
        assert claimed["allocation"]["observed"] is False
    assert len(set(dispatched)) == 1

    def recover(**request):
        with psycopg.connect(target_dsn, autocommit=True) as connection:
            return create_generation(connection, **request)

    assert reconcile(opened, recover) == dispatched[0]
    assert reconcile(opened, recover) == dispatched[0]
    with store.transaction() as session:
        claimed, = store.ops(session, mirror_id)
        assert claimed["allocation"]["observed"] is True
    assert Mirror.model_validate(service.get_mirror(mirror_id)) == Mirror.model_validate(before)
    assert_unavailable(target_dsn, mirror_id)


@pytest.mark.integration
@pytest.mark.parametrize("change", ["withdrawn", "disabled", "revision", "retired", "missing_receipt", "catalog", "history"])
def test_native_rechecks_the_current_open_claim_after_dispatch(opened, target_dsn, change):
    store, mirror_id, _, authority = opened
    if change == "history":
        with store.transaction() as session:
            session.add(HistoryGateRow(mirror_id=mirror_id, history_epoch="epoch", status="available",
                                       lower_commit_seq=0, lower_entry_seq=0))

    def dispatch(**request):
        with psycopg.connect(target_dsn, autocommit=True) as connection:
            generation_id = create_generation(connection, **request)
        with store.transaction() as session:
            if change == "withdrawn":
                service.reconcile_references(session, channel_id="channel", channel_version=2, object_ids=[])
            elif change in {"revision", "disabled"}:
                row, = store.list(session)
                row["enabled"] = change != "disabled"
                row["control"]["control_revision"] += (change == "revision")
                store.save(session, row)
            elif change == "retired":
                state = load_binding(session, authority.source_id)
                save_binding(session, dict(state, owner_epoch=4, runtime_instance_id="replacement"))
            elif change == "catalog":
                session.get(CatalogObjectRow, "orders").is_present = False
            elif change == "history":
                History(session_factory=None, target=object()).invalidate_history(
                    session, mirror_ids=[mirror_id], reason="capture gap", operation_id="history-reset",
                )
        return None if change == "missing_receipt" else generation_id

    with pytest.raises(AppError) as failure:
        reconcile(opened, dispatch)
    assert failure.value.code == "MIRROR_CONTROL_CONFLICT"
    with store.transaction() as session:
        claimed, = store.ops(session, mirror_id)
        assert claimed["allocation"]["observed"] is False
    assert_unavailable(target_dsn, mirror_id)
    if change != "missing_receipt":
        with pytest.raises(AppError) as repeated:
            reconcile(opened, lambda **_: pytest.fail("stale claim dispatched"))
        assert repeated.value.code == "MIRROR_CONTROL_CONFLICT"


@pytest.mark.integration
def test_native_unverified_and_changed_binding_cannot_dispatch(opened):
    store, mirror_id, _, _ = opened
    with pytest.raises(AppError):
        reconcile(opened, lambda **_: pytest.fail("unverified claim dispatched"), verifier=lambda **_: False)
    with store.transaction() as session:
        pending, = store.ops(session, mirror_id)
        assert "allocation" not in pending
    with pytest.raises(TimeoutError):
        reconcile(opened, lambda **_: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(AppError) as failure:
        reconcile(opened, lambda **_: pytest.fail("changed binding dispatched"), schema_fingerprint="other")
    assert failure.value.code == "MIRROR_CONTROL_CONFLICT"


@pytest.mark.integration
def test_native_prepared_fence_cannot_substitute_for_accepted_owner(opened):
    store, mirror_id, _, authority = opened
    with store.transaction() as session:
        state = load_binding(session, authority.source_id)
        save_binding(session, dict(state, owner_epoch=0, runtime_instance_id=None,
                                   pending_allocation={"authority": asdict(authority)}))
    with pytest.raises(AppError) as failure:
        reconcile(opened, lambda **_: pytest.fail("unpromoted owner dispatched"))
    assert failure.value.code == "MIRROR_CONTROL_CONFLICT"
    with store.transaction() as session:
        pending, = store.ops(session, mirror_id)
        assert "allocation" not in pending
