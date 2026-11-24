"""Native gates for the durable open operation and isolated target bootstrap."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from importlib import import_module
import os
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from backend.core.errors import AppError
from backend.core.time import utc_now
from backend.metadata.capture.store import load_binding, save_binding, save_operation
from backend.metadata.models import CatalogObjectRow, SourceCaptureBindingRow, SourceCaptureOperationRow, SourceRow
from backend.metadata.mirrors import reconciliation, service
from backend.metadata.mirrors.bootstrap import create_generation, install
from backend.metadata.mirrors.diagnostic_store import DiagnosticRow
from backend.metadata.mirrors.history import History
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import MirrorOperationRow, MirrorRow
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.schemas import Mirror
from backend.metadata.mirrors.store import SqlMirrorStore
from backend.metadata.mirrors.types import AnchoredProfile, Authority, PartitionIdentity
from backend.tests.mirror_inventory import inventory


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
        for model in (SourceRow, CatalogObjectRow, SourceCaptureBindingRow, SourceCaptureOperationRow, MirrorRow,
                      MirrorOperationRow, HistoryGateRow, HistoryInvalidationRow, RecoveryRow, DiagnosticRow):
            model.__table__.create(engine)
        store = SqlMirrorStore()
        store.transaction = sessionmaker(engine).begin
        monkeypatch.setattr(service, "_store", store)
        monkeypatch.setattr(service, "persist_audit_event", lambda **kwargs: None)
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
        opened = service.enable_for_object("orders", actor_user_id="operator")
        mirror_id = opened["mirror"]["id"]
        prepare_fence(target_dsn, mirror_id, authority)
        with store.transaction() as session:
            state = asdict(authority)
            state["binding_id"] = state.pop("resource_binding_id")
            save_binding(session, dict(state, capture_generation=1, desired="configured",
                                       published_scope=service.read_published_scope(session, source_id)))
        yield store, mirror_id, opened["operation_id"], authority
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
    return reconciliation.reconcile_open_generation(mirror_id=mirror_id, operation_id=operation_id,
                                             binding=reconciliation.OpenGenerationBinding(**binding),
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
    pending, applied = reconciliation.current_open_preparations(
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
        reconciliation.require_current_open_allocations(session, authority=authority, allocations=[(replacement, generation_id)])
        recovery = session.get(RecoveryRow, recovery_id)
        recovery.journal = dict(recovery.journal, submission_command=dict(submission, generation_id='superseded'))
    with store.transaction() as session, pytest.raises(AppError, match='MIRROR_CONTROL_CONFLICT'):
        reconciliation.require_current_open_allocations(session, authority=authority, allocations=[(replacement, generation_id)])
    assert initial_operation_id != recovery_id


@pytest.mark.integration
def test_concurrent_catalog_enables_create_one_open(opened):
    store, _, _, authority = opened
    now = utc_now()
    with store.transaction() as session:
        session.add(CatalogObjectRow(id="items", source_id=authority.source_id, locator_key="items",
                                     object_type="table", schema_name="sales", name="items",
                                     created_at=now, updated_at=now))
    start = Barrier(4, timeout=10)

    def enable(index):
        start.wait()
        if index % 2:
            result = service.enable_for_object("items", actor_user_id="operator")
            return result["mirror"]["id"], result["operation_id"]
        result = service.set_enabled_for_object("items", source_id=authority.source_id, enabled=True,
                                                can_read=True, actor_user_id="operator")
        return result["mirror"]["mirror_id"], result["operation_id"]

    with ThreadPoolExecutor(4) as workers:
        identities = set(workers.map(enable, range(4)))
    (mirror_id, operation_id), = identities
    with store.transaction() as session:
        op, = store.ops(session, mirror_id)
        assert (op["kind"], op["id"], op["control_revision"]) == ("open", operation_id, 1)


@pytest.mark.integration
def test_sql_inventory_and_catalog_picker_keep_observed_and_retained_bindings(opened):
    store, mirror_id, operation_id, authority = opened
    with store.transaction() as session:
        operation, = store.ops(session, mirror_id)
        bound = dict(authority=asdict(authority), object_id="orders", table_identity="orders",
                     qualified_table="sales.orders", history_epoch="epoch", schema_fingerprint="schema",
                     partition_identity={"partition": 0})
        operation["allocation"] = dict(generation_id="copy", observed=True, mirror_revision=1, binding=bound)
        store.save_op(session, operation)
        state = load_binding(session, authority.source_id)
        state["applied_revision"] = authority.control_revision
        state["incremental_snapshots"] = dict(active=None, generations={"copy": dict(
            id="scan", receipt=True, state="catching_up", scan=dict(offset=1, timestamp=1700000000000),
            completion=dict(offset=2, timestamp=1700000001000), binding=dict(
                authority=asdict(authority), mirror_id=mirror_id, mirror_revision=1,
                allocation_operation_id=operation_id, generation_id="copy", table_identity="orders",
                qualified_table="sales.orders", history_epoch="epoch", schema_fingerprint="schema",
                data_partition={"partition": 0},
            ),
        )})
        save_binding(session, state)
    # Exercise adoption of an existing snapshot whose saved status still says waiting.
    migration = import_module("backend.alembic.versions.0104_mirror_effective_status")
    with store.transaction() as session:
        connection = session.connection()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
        assert "ix_source_mirrors_effective_status" in {
            index["name"] for index in inspect(connection).get_indexes("source_mirrors")
        }
        assert connection.exec_driver_sql("SELECT effective_status FROM source_mirrors").scalar_one() == "catching_up"
    page = inventory(status="catching_up", q="sales.orders", limit=1)
    assert page["total"] == 1 and page["items"][0]["id"] == mirror_id
    assert inventory(status="waiting")["total"] == 0
    assert inventory(status="catching_up", offset=1)["items"] == []
    assert inventory(status="catching_up", offset=1)["total"] == 1
    with store.transaction() as session:
        source = session.get(SourceRow, authority.source_id)
        source.engine = "mysql"
        session.add(CatalogObjectRow(id="unbound", source_id=authority.source_id, locator_key="unbound",
                                     object_type="table", schema_name="sales", name="unbound",
                                     created_at=utc_now(), updated_at=utc_now()))
    tables = service.list_catalog_mirror_tables(visible_ids={authority.source_id}, object_id=None, q=None,
                                                can_read=True, can_write=True, limit=10, offset=0)
    assert tables["total"] == 1 and tables["items"][0]["object_id"] == "orders"
    assert tables["items"][0]["mirror"]["can_disable"] is True
    hidden = service.list_catalog_mirror_tables(visible_ids=set(), object_id=None, q=None,
                                                can_read=True, can_write=True, limit=10, offset=0)
    assert hidden["total"] == 0


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
@pytest.mark.parametrize("change", ["disabled", "revision", "retired", "missing_receipt", "catalog", "history"])
def test_native_rechecks_the_current_open_claim_after_dispatch(opened, target_dsn, change):
    store, mirror_id, operation_id, authority = opened
    if change == "history":
        with store.transaction() as session:
            session.add(HistoryGateRow(mirror_id=mirror_id, history_epoch="epoch", status="available",
                                       lower_commit_seq=0, lower_entry_seq=0))

    def dispatch(**request):
        with psycopg.connect(target_dsn, autocommit=True) as connection:
            generation_id = create_generation(connection, **request)
        if change == "disabled":
            service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
        with store.transaction() as session:
            if change == "revision":
                row = store.get(session, mirror_id)
                row["control"]["control_revision"] += 1
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
        claimed, = (op for op in store.ops(session, mirror_id) if op["id"] == operation_id)
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


@pytest.mark.integration
def test_reopen_after_verified_table_gap_recovers_interrupted_invalidation(opened):
    store, mirror_id, original_operation, authority = opened
    previous_generation = uuid4().hex
    partition = asdict(PartitionIdentity("cluster", "orders", 0))
    epoch = "published-epoch"
    with store.transaction() as session:
        previous, = store.ops(session, mirror_id)
        store.save_op(session, dict(previous, state="applied", allocation=dict(binding=dict(partition_identity=partition)),
                                    publication_receipt=dict(generation_id=previous_generation, history_epoch=epoch,
                                                             authority=asdict(authority))))
        row = session.get(MirrorRow, mirror_id)
        row.state = dict(row.state, published_generation_id=previous_generation, history_epoch=epoch)
        session.add(HistoryGateRow(mirror_id=mirror_id, history_epoch=epoch, status="available",
                                   lower_commit_seq=0, lower_entry_seq=0))
        session_factory = sessionmaker(session.get_bind())
    service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
    reopen = service.set_enabled(mirror_id, enabled=True, actor_user_id="operator")
    with store.transaction() as session:
        scope = service.read_published_scope(session, authority.source_id)
        state = load_binding(session, authority.source_id)
        save_binding(session, dict(state, published_scope=scope))

    boundaries = {reopen["operation_id"]: 8}

    class Target:
        attempts = 0

        def invalidate(self, *, operation_id, transitions, reason, replay_only):
            assert reason == "table_gap" and operation_id in boundaries
            assert transitions[0]["start_offset"] == boundaries[operation_id]
            assert transitions[0]["partition_identity"] == partition
            self.attempts += 1
            if self.attempts == 1:
                raise TimeoutError("target acknowledgment lost")
            return True

    history = History(session_factory=session_factory, target=Target())
    request = dict(authority=authority, published_scope=scope, mirror_id=mirror_id,
                   mirror_revision=reopen["mirror"]["control"]["control_revision"], operation_id=original_operation,
                   evidence_ref="sha256:" + "a" * 64, start_offset=8, partition_identity=partition, history=history)
    with pytest.raises(AppError, match="MIRROR_CONTROL_CONFLICT"):
        reconciliation.request_reopen_baseline(**dict(request, partition_identity=dict(partition, topic_incarnation_id="other")))
    with pytest.raises(TimeoutError, match="acknowledgment lost"):
        reconciliation.request_reopen_baseline(**request)
    with store.transaction() as session:
        assert session.get(HistoryGateRow, mirror_id).status == "invalidating"
    pending, retained = reconciliation.current_open_preparations(
        authority=authority, published_scope=scope, observe_committed=pytest.fail, history=history)
    assert not retained
    baseline, = pending
    assert baseline["operation_id"] == reopen["operation_id"]
    assert baseline["reopen_baseline"] and baseline["start_offset"] == 8 and baseline["partition_identity"] == partition
    assert baseline["history_epoch"] != epoch
    assert service.get_mirror(mirror_id)["published_generation_id"] == previous_generation
    with store.transaction() as session:
        assert session.get(HistoryGateRow, mirror_id).status == "available"
    reconciliation.request_reopen_baseline(**request)
    replay, _ = reconciliation.current_open_preparations(
        authority=authority, published_scope=scope, observe_committed=pytest.fail, history=history)
    assert replay == pending

    # Interrupt this replacement, skip additional records, then request another open.
    service.set_enabled(mirror_id, enabled=False, actor_user_id="operator")
    latest = service.set_enabled(mirror_id, enabled=True, actor_user_id="operator")
    boundaries[latest["operation_id"]] = 12
    current = replace(authority, control_revision=authority.control_revision+2)
    with store.transaction() as session:
        scope = service.read_published_scope(session, authority.source_id)
        state = load_binding(session, authority.source_id)
        state.update(control_revision=current.control_revision, published_scope=scope)
        save_binding(session, state)
    with pytest.raises(AppError, match="MIRROR_CONTROL_CONFLICT"):
        reconciliation.current_open_preparations(authority=current, published_scope=scope, observe_committed=pytest.fail,
                                          history=history)
    with store.transaction() as session:
        stamp = {k: state[k] for k in ("source_id", "binding_id", "owner_epoch", "runtime_instance_id",
                                       "credential_revision", "control_revision", "capture_generation")}
        command = dict(stamp, kind="reconcile", operation_id="latest-scope", published_scope=scope)
        save_operation(session, command)
        fresh = dict(start_offset=12, partition_identity=partition, mirror_revision=scope[0]["mirror_revision"],
                     evidence_ref="sha256:"+"b"*64)
        state["scope_fence"] = dict(authority=stamp, operation_id=command["operation_id"], mirror_receipts={mirror_id: "fence"},
                                    table_boundaries={mirror_id: fresh})
        save_binding(session, state)
    pending, _ = reconciliation.current_open_preparations(authority=current, published_scope=scope,
                                                  observe_committed=pytest.fail, history=history)
    new, = pending
    assert new["operation_id"] == latest["operation_id"] and new["start_offset"] == 12
    assert new["history_epoch"] not in {epoch, baseline["history_epoch"]}
    assert service.get_mirror(mirror_id)["published_generation_id"] == previous_generation


@pytest.mark.integration
def test_pending_allocation_recovers_after_a_sibling_switch(opened):
    store, mirror_id, original_operation, authority = opened
    epoch = reconciliation.initial_history_epoch(mirror_id)
    reconcile(opened, lambda **request: request["generation_id"], history_epoch=epoch)
    with store.transaction() as session:
        original, = store.ops(session, mirror_id)
        partition = original["allocation"]["binding"]["partition_identity"]
        created = utc_now()
        session.add(CatalogObjectRow(id="items", source_id=authority.source_id, locator_key="items",
                                     object_type="table", schema_name="sales", name="items",
                                     created_at=created, updated_at=created))
        sessions = sessionmaker(session.get_bind())
    sibling = service.enable_for_object("items", actor_user_id="operator")
    current = replace(authority, control_revision=authority.control_revision + 1)
    with store.transaction() as session:
        scope = service.read_published_scope(session, authority.source_id)
        state = load_binding(session, authority.source_id)
        state.update(published_scope=scope, control_revision=current.control_revision)
        stamp = {key: state[key] for key in ("source_id", "binding_id", "runtime_instance_id", "owner_epoch",
                                              "control_revision", "credential_revision", "capture_generation")}
        command = dict(stamp, kind="reconcile", operation_id="expanded-scope", published_scope=scope)
        save_operation(session, command)
        fence = dict(authority=stamp, operation_id=command["operation_id"],
                     mirror_receipts={entry["mirror_id"]: "sha256:" + "a" * 64 for entry in scope})
        save_binding(session, dict(state, scope_fence=fence))

    class Target:
        def invalidate(self, *, operation_id, transitions, reason, replay_only):
            assert operation_id != original_operation and reason == "table_gap" and not replay_only
            change, = transitions
            assert change["mirror_id"] == mirror_id and change["old_epoch"] == epoch
            assert change["start_offset"] == 9 and change["partition_identity"] == partition
            return True

    history = History(session_factory=sessions, target=Target())
    prepare = dict(authority=current, published_scope=scope, observe_committed=pytest.fail, history=history)
    with pytest.raises(AppError, match="MIRROR_CONTROL_CONFLICT"):
        reconciliation.current_open_preparations(**prepare, selected_table_ids={"orders"})
    # A checked interval may lack conclusive coverage before any first publication.
    reconciliation.record_continuity_receipt(authority=current, scope=scope, mirror_id=mirror_id, check_id=original_operation,
                                      decision=dict(result="unknown", observed_at=utc_now().isoformat(),
                                                    evidence_ref="sha256:" + "b" * 64))
    boundary = dict(start_offset=9, partition_identity=partition, mirror_revision=1, evidence_ref="sha256:" + "c" * 64)
    with store.transaction() as session:
        save_binding(session, dict(state, scope_fence=dict(fence, table_boundaries={mirror_id: boundary})))
    pending, retained = reconciliation.current_open_preparations(**prepare)
    assert not retained
    orders, = [entry for entry in pending if entry["mirror_id"] == mirror_id]
    assert orders["start_offset"] == 9 and orders["operation_id"] != original_operation and orders["history_epoch"] != epoch
    items, = [entry for entry in pending if entry["mirror_id"] == sibling["mirror"]["id"]]
    assert items["operation_id"] == sibling["operation_id"] and not items.get("reopen_baseline")
    assert reconciliation.current_open_preparations(**prepare) == (pending, retained)
    assert service.set_enabled(mirror_id, enabled=True, actor_user_id="operator")["operation_id"] == original_operation
    detail = service.get_mirror_detail(mirror_id)["mirror"]
    assert detail["open_request"]["operation_id"] == original_operation
    assert detail["open_request"]["outcome"] == "awaiting_publication"
    assert detail["blocker"] is None and detail["history_epoch"] is None
    assert [e["kind"] for e in service.get_mirror_journal(mirror_id)["items"]] == [
        "continuity_gap", "continuity_unknown", "open",
    ]



@pytest.mark.integration
@pytest.mark.parametrize("outcome", ["continuous", "gap"])
def test_recheck_keeps_open_and_attributes_later_proof(opened, outcome):
    store, mid, published_open, authority = opened
    generation, epoch, certificate = "published-copy", "established-epoch", "certificate-ref"
    partition = asdict(PartitionIdentity("cluster", "orders", 0))
    with store.transaction() as session:
        published, = store.ops(session, mid)
        receipt = dict(generation_id=generation, history_epoch=epoch, certificate_ref=certificate, authority=asdict(authority))
        store.save_op(session, dict(published, state="applied", publication_receipt=receipt,
                                    allocation=dict(binding=dict(partition_identity=partition))))
        store.save(session, dict(store.get(session, mid), published_generation_id=generation, history_epoch=epoch))
        session.add(HistoryGateRow(mirror_id=mid, history_epoch=epoch, status="available", lower_commit_seq=0, lower_entry_seq=0))
        factory = sessionmaker(session.get_bind())
    service.set_enabled(mid, enabled=False, actor_user_id="user")
    reopen = service.set_enabled(mid, enabled=True, actor_user_id="user")["operation_id"]
    with store.transaction() as session:
        scope = service.read_published_scope(session, authority.source_id)
        state = load_binding(session, authority.source_id)
        save_binding(session, dict(state, published_scope=scope, applied_revision=authority.control_revision))

    def decision(result, digit):
        return dict(result=result, observed_at=utc_now().isoformat(), evidence_ref="sha256:" + digit * 64)

    def check(request, result, digit):
        return reconciliation.record_continuity_receipt(authority=authority, scope=scope, mirror_id=mid, check_id=request,
                                                 decision=decision(result, digit), published_operation_id=published_open)

    opts = dict(expected_epoch=epoch, expected_revision=3, actor_user_id="writer")
    with pytest.raises(AppError, match="MIRROR_CONTROL_CONFLICT"):
        service.request_recheck(mid, **opts)
    with store.transaction() as session:
        command = dict(load_binding(session, authority.source_id))
    reconciliation.table_prerequisite_check(command, table="sales.orders", cause="permission", passed=False, request_id=reopen)
    permission = service.request_recheck(mid, **opts)["operation_id"]
    for _ in range(2):
        reconciliation.table_prerequisite_check(command, table="sales.orders", cause="permission", passed=False, request_id=permission)
    reconciliation.table_prerequisite_check(command, table="sales.orders", cause="permission", passed=True, request_id=permission)
    detail = service.get_mirror_detail(mid)["mirror"]
    assert detail["blocker"] is None
    assert detail["open_request"]["outcome"] == "awaiting_continuity"
    permission_events = [e for e in service.get_mirror_journal(mid)["items"]
                         if e["category"] == "observation" and e["operation_id"] == permission]
    assert [e["kind"] for e in permission_events] == ["permission_verified", "permission_blocked"]
    check(reopen, "unknown", "1")
    first = service.request_recheck(mid, **opts)["operation_id"]
    assert first == service.request_recheck(mid, **opts)["operation_id"]
    check(first, "unknown", "2")
    assert service.get_mirror_detail(mid)["mirror"]["can_retry"]
    second = service.request_recheck(mid, **opts)["operation_id"]
    assert first != second
    conclusive = decision(outcome, "3")
    assert not reconciliation.record_continuity_receipt(authority=authority, scope=scope, mirror_id=mid, check_id=first,
                                                 decision=conclusive, published_operation_id=published_open)
    if outcome == "continuous":
        candidate = SimpleNamespace(mirror_id=mid, operation_id=published_open, certificate_ref=certificate,
                                    generation_id=generation, binding=SimpleNamespace(authority=authority,
                                                                                     history_epoch=epoch, table_identity="orders"))
        reconciliation.confirm_retained_opens(authority=authority, published_scope=scope, candidates=[candidate],
                                       decisions={mid: conclusive}, checks={mid: first})
    else:
        history = History(session_factory=factory, target=SimpleNamespace(invalidate=lambda **kwargs: True))
        reconciliation.request_reopen_baseline(authority=authority, published_scope=scope, mirror_id=mid, mirror_revision=3,
                                        operation_id=published_open, partition_identity=partition, start_offset=10,
                                        history=history, check_id=first, observed_at=conclusive["observed_at"],
                                        evidence_ref=conclusive["evidence_ref"])
    check(second, "unknown", "4")
    check(second, "unknown", "4")
    assert check(second, "gap", "5") in {"recorded", "retained"}
    detail = service.get_mirror_detail(mid)["mirror"]
    assert detail["published_generation_id"] == generation and detail["blocker"] is None
    assert detail["open_request"]["outcome"] == ("continuity_verified" if outcome == "continuous" else "awaiting_publication")
    assert (detail["history_epoch"] == epoch) == (outcome == "continuous")
    events = service.get_mirror_journal(mid)["items"]
    requests = {e["operation_id"]: e for e in events if e["category"] == "request"}
    assert requests[first]["outcome"] == "continuity_unknown"
    assert requests[second]["outcome"] == "resolved_by_evidence"
    assert requests[second]["related_operation_id"] == first
    late = [e for e in events if e["operation_id"] == second and e["category"] == "observation"]
    assert [e["kind"] for e in late] == ["continuity_gap", "continuity_unknown"]
    assert len(detail["journal"]["items"]) == 3
    remaining = service.get_mirror_journal(mid, before=detail["journal"]["next_cursor"])["items"]
    assert events == detail["journal"]["items"] + remaining
