"""History loss receipts and the restricted target write boundary on PostgreSQL."""

from dataclasses import asdict, replace
from secrets import token_urlsafe
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from backend.core.time import utc_now
from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.bootstrap import create_generation, install, install_authority
from backend.metadata.mirrors.history import History, SqlHistoryTarget
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.publication import Publication, persist_verified_certificate
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.recovery import Recovery
from backend.metadata.mirrors.recovery_store import RecoveryRow
from backend.metadata.mirrors.service import MirrorError
from backend.metadata.mirrors.types import AnchoredProfile, Authority, PartitionIdentity, ReadCommittedBounds, Record, SealedScan
from backend.metadata.models import SourceCaptureBindingRow, SourceRow
from backend.tests.test_capture_preparation import management_engine as management_engine, native_target as native_target
from backend.tests.test_mirror_generation_allocation import target_dsn as target_dsn
from backend.tests.test_mirror_publication_retry import FixtureVerifier, observation_request


AUTHORITY = Authority("source", "binding", 3, "runtime", 4, 2, "old-capture")
AFFECTED = "mir_" + "a" * 32
RETAINED = "mir_" + "b" * 32
EPOCH = "original-epoch"

pytestmark = pytest.mark.integration


@pytest.fixture
def history_loss(native_target, management_engine):
    for model in (SourceRow, SourceCaptureBindingRow, MirrorRow, HistoryGateRow, HistoryInvalidationRow):
        model.__table__.create(management_engine)
    factory = sessionmaker(management_engine)
    with psycopg.connect(native_target, autocommit=True) as admin:
        engines = []
        for role in ("refraq_mirror_applier", "refraq_mirror_gateway"):
            password = token_urlsafe(24)
            admin.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
            engine = create_engine("postgresql+psycopg://", creator=lambda role=role, password=password:
                                   psycopg.connect(native_target, user=role, password=password))
            engines.append(engine)
        applier, gateway = engines
        target = SqlHistoryTarget(engine=gateway, invalidation_engine=applier, timeout_ms=3000)

        def authorize(*, execution_user_id, source_id, session=None):
            assert (execution_user_id, source_id) == ("reader", AUTHORITY.source_id)

        history = History(session_factory=factory, target=target, authorize_source_read=authorize)
        reads = Reads(gateway, authorize_source_read=authorize, verify_terminal_proof=pytest.fail)
        now = utc_now()
        with factory.begin() as session:
            session.add(SourceRow(id=AUTHORITY.source_id, key="source", locator_key="source", name="Source",
                                  kind="database", created_at=now, updated_at=now))
            session.flush()
            for mirror_id, table in ((AFFECTED, "orders"), (RETAINED, "items")):
                session.add(MirrorRow(id=mirror_id, source_id=AUTHORITY.source_id, table_identity=table,
                                      enabled=True, state={}))
            session.flush()
        try:
            yield admin, factory, history, target, Application(applier), Publication(applier), reads
        finally:
            for engine in engines:
                engine.dispose()


def allocation(mirror_id, table, *, authority=AUTHORITY, epoch=EPOCH):
    return dict(mirror_id=mirror_id, table_identity=table, generation_id=uuid4().hex, authority=authority,
                operation_id=uuid4().hex, history_epoch=epoch, schema_fingerprint="schema",
                columns={"id": "bigint"}, key_columns=("id",), start_offset=-1,
                partition_identity=PartitionIdentity("cluster", uuid4().hex, 0))


def certificate_request(request):
    identity = {key: request[key] for key in ("operation_id", "authority", "generation_id")}
    certificate = dict(
        {key: request[key] for key in ("operation_id", "generation_id", "table_identity", "schema_fingerprint")},
        capture_generation=request["authority"].capture_generation,
        partition_identity=asdict(request["partition_identity"]), end_offset=0, source_completion="snapshot",
        producer_exclusion="exclusion", durable_source_checkpoint="checkpoint", ordered_delivery_proof="coverage",
        key_fingerprint="key", empty_table_proof=False,
    )
    return dict(identity, certificate=certificate)


def delivery(application, request, offset=None, *, origin="live"):
    records = []
    if offset is not None:
        row = {"id": offset + 1}
        records.append(Record(offset, request["table_identity"], request["authority"].capture_generation,
                              "upsert", origin, row, row))
    return application.apply_batch(**{key: request[key] for key in ("authority", "generation_id", "partition_identity")},
                                   records=records)


def begin_invalidation(history, factory, *, operation_id, reason="history_loss", mirror_ids=(AFFECTED,)):
    with factory.begin() as session:
        return history.invalidate_history(session, mirror_ids=mirror_ids, reason=reason, operation_id=operation_id)


def history_error(code):
    return pytest.raises(MirrorError, check=lambda error: error.code == code)


@pytest.mark.parametrize("receipt_case", [
    "legacy", "missing", "missing-target", "missing-mirror", "mismatched", "wrong-transition", "pending",
    "wrong-reason", "wrong-epoch", "unavailable-peer", "foreign-peer", "stale-peer", "fenced", "commit-interrupted",
])
def test_replacement_publication_requires_current_fenced_loss(history_loss, receipt_case, monkeypatch):
    admin, factory, history, target, application, publication, reads = history_loss
    RecoveryRow.__table__.create(factory.kw["bind"])
    operation_id = "replacement"
    original = allocation(RETAINED, "items")
    for initial in (allocation(AFFECTED, "orders"), original):
        create_generation(admin, **initial)
        delivery(application, initial, 0, origin="baseline")
        certified = certificate_request(initial)
        persist_verified_certificate(admin, **certified, verifier=FixtureVerifier())
        publication.publish_generation(**certified)
        with factory.begin() as session:
            history.initialize_gate(session, mirror_id=initial["mirror_id"], history_epoch=EPOCH)
            session.get(MirrorRow, initial["mirror_id"]).state = dict(
                published_generation_id=initial["generation_id"], capture_generation=AUTHORITY.capture_generation,
                history_epoch=EPOCH, status="ready",
            )

    delivery(application, original, 1)
    read_identity = dict(mirror_id=RETAINED, execution_user_id="reader")
    old_pin = reads.acquire_pin(run_id="old-run", **read_identity)

    mirror_ids = (AFFECTED,) if receipt_case == "missing-mirror" else (RETAINED, AFFECTED)
    changes = begin_invalidation(history, factory, operation_id=operation_id, mirror_ids=mirror_ids)
    epoch = EPOCH if receipt_case == "missing-mirror" else changes[1]["history_epoch"]
    if receipt_case in {"legacy", "pending", "missing-target"}:
        if receipt_case != "missing-target":
            options = {"reason": "history_loss"} if receipt_case == "pending" else {}
            assert target.invalidate(operation_id=operation_id, transitions=changes, **options) is True
        with factory.begin() as session:
            if receipt_case != "pending":
                session.get(HistoryInvalidationRow, operation_id).status = "applied"
            for mirror_id in (AFFECTED, RETAINED):
                session.get(HistoryGateRow, mirror_id).status = "available"
    else:
        history.consume_invalidation(operation_id=operation_id)
    if receipt_case == "stale-peer":
        begin_invalidation(history, factory, operation_id="later-retention", reason="retention")
        history.consume_invalidation(operation_id="later-retention")

    authority = replace(AUTHORITY, control_revision=AUTHORITY.control_revision + 1, capture_generation="new-capture")
    install_authority(admin, mirror_id=RETAINED, expected_authority=AUTHORITY, authority=authority,
                      exclusion_proof="fixture", verify_exclusion=lambda *_: True)
    target_epoch = EPOCH if receipt_case == "missing-target" else epoch
    replacement = dict(allocation(RETAINED, "items", authority=authority, epoch=target_epoch), operation_id=operation_id)
    create_generation(admin, **replacement)
    delivery(application, replacement, 0, origin="baseline")
    certified = certificate_request(replacement)
    persist_verified_certificate(admin, **certified, verifier=FixtureVerifier())
    with factory.begin() as session:
        receipt = session.get(HistoryInvalidationRow, operation_id)
        if receipt_case == "missing":
            session.delete(receipt)
        elif receipt_case == "mismatched":
            receipt.transitions = changes[1:]
        elif receipt_case == "wrong-transition":
            receipt.transitions = [changes[0] | {"old_epoch": "different-old-epoch"}, changes[1]]
        elif receipt_case == "wrong-reason":
            receipt.reason = "retention"
        elif receipt_case == "unavailable-peer":
            session.get(HistoryGateRow, AFFECTED).status = "invalidating"
        elif receipt_case == "foreign-peer":
            now = utc_now()
            session.add(SourceRow(id="other-source", key="other-source", locator_key="other-source",
                                  name="Other Source", kind="database", created_at=now, updated_at=now))
            session.flush()
            session.get(MirrorRow, AFFECTED).source_id = "other-source"
        journal_epoch = "different-journal-epoch" if receipt_case == "wrong-epoch" else epoch
        session.add(RecoveryRow(operation_id=operation_id, source_id=AUTHORITY.source_id, mirror_id=RETAINED,
                                identity=operation_id, journal=dict(state="dispatched", replacement_epoch=journal_epoch,
                                generation_id=replacement["generation_id"], capture_generation=authority.capture_generation,
                                submission_uncertain=True)))

    def published_pointer():
        return admin.execute("SELECT published_generation_id FROM source_mirror_state.mirrors WHERE id = %s",
                             (RETAINED,)).fetchone()

    def mirror_state():
        with factory() as session:
            return session.get(MirrorRow, RETAINED).state

    service = Recovery(session_factory=factory, history=history, retry_delays=(1,), publication=publication)
    completion = dict(operation_id=operation_id, authority=authority, certificate=certified["certificate"])
    old_state = mirror_state()
    assert published_pointer() == (original["generation_id"],)
    if receipt_case == "fenced":
        lock_order = [(SourceRow, AUTHORITY.source_id), (HistoryGateRow, AFFECTED), (HistoryGateRow, RETAINED),
                      (HistoryInvalidationRow, operation_id)]
        observed_locks = []
        engine = factory.kw["bind"]
        acknowledge = target.invalidate
        publish = publication.publish_generation
        stages = []

        def record_lock(_connection, _cursor, statement, parameters, _context, _executemany):
            if statement.endswith("FOR UPDATE"):
                observed_locks.append(next(iter(parameters.values())))

        def assert_locks_held():
            assert observed_locks == [key for _, key in lock_order]
            for model, key in lock_order:
                with factory() as contender, pytest.raises(DBAPIError, check=lambda error: error.orig.sqlstate == "55P03"):
                    contender.get(model, key, with_for_update={"nowait": True})

        def acknowledge_while_locked(**kwargs):
            assert_locks_held()
            stages.append("acknowledged")
            return acknowledge(**kwargs)

        def publish_while_locked(**kwargs):
            assert_locks_held()
            stages.append("published")
            return publish(**kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(target, "invalidate", acknowledge_while_locked)
            patch.setattr(publication, "publish_generation", publish_while_locked)
            event.listen(engine, "before_cursor_execute", record_lock)
            try:
                assert service.publish_replacement(**completion) == replacement["generation_id"]
            finally:
                event.remove(engine, "before_cursor_execute", record_lock)
        assert stages == ["acknowledged", "published"]
    elif receipt_case == "commit-interrupted":
        original_journal = service.get_operation(operation_id)

        def interrupt_commit(session):
            session.flush()
            with pytest.raises(psycopg.errors.LockNotAvailable), admin.transaction():
                admin.execute("SELECT id FROM source_mirror_state.mirrors WHERE id = %s FOR UPDATE NOWAIT", (RETAINED,))
            raise RuntimeError("Management commit interrupted")

        event.listen(factory, "before_commit", interrupt_commit)
        try:
            with pytest.raises(RuntimeError, match="Management commit interrupted"):
                service.publish_replacement(**completion)
        finally:
            event.remove(factory, "before_commit", interrupt_commit)
        assert published_pointer() == (replacement["generation_id"],)
        assert mirror_state() == old_state
        assert service.get_operation(operation_id) == original_journal
        monkeypatch.setattr(publication, "publish_generation", lambda **kwargs: pytest.fail("Retry republished"))
        contradictory_certificate = dict(certified["certificate"], empty_table_proof=0)
        with history_error("MIRROR_PUBLICATION_BLOCKED"):
            service.publish_replacement(**dict(completion, certificate=contradictory_certificate))
        assert mirror_state() == old_state
        assert service.get_operation(operation_id) == original_journal
        assert service.publish_replacement(**completion) == replacement["generation_id"]

    if receipt_case in {"fenced", "commit-interrupted"}:
        assert published_pointer() == (replacement["generation_id"],)
        bound = target.capture_bound(mirror_id=RETAINED)
        assert mirror_state() == dict(old_state, published_generation_id=replacement["generation_id"],
                                      capture_generation=authority.capture_generation, history_epoch=epoch,
                                      retained_lower_bound=bound["lower_bound"], committed_upper_bound=bound["upper_bound"])
        assert reads.acquire_pin(run_id="old-run", **read_identity) == old_pin
        old_page = reads.read_page(pin=old_pin, execution_user_id="reader", after_key=None, limit=10)
        assert (old_page["freshness"], old_page["rows"]) == ("stale", [{"id": 1}, {"id": 2}])
        new_pin = reads.acquire_pin(run_id="new-run", **read_identity)
        assert new_pin.generation_id == replacement["generation_id"]
        assert reads.read_page(pin=new_pin, execution_user_id="reader", after_key=None, limit=10)["rows"] == [{"id": 1}]
        journal = service.get_operation(operation_id)
        assert journal["state"] == "applied"
        assert journal["submission_uncertain"] is False
        begin_invalidation(history, factory, operation_id="later-retention", reason="retention", mirror_ids=(RETAINED,))
        history.consume_invalidation(operation_id="later-retention")
        monkeypatch.setattr(target, "invalidate", lambda **kwargs: pytest.fail("Historical retry called the target"))
        monkeypatch.setattr(publication, "publish_generation", lambda **kwargs: pytest.fail("Historical retry republished"))
        monkeypatch.setattr(publication, "observe_committed", lambda **kwargs: pytest.fail("Historical retry observed target"))
        with history_error("MIRROR_PUBLICATION_BLOCKED"):
            service.publish_replacement(**dict(completion, authority=AUTHORITY))
        with history_error("MIRROR_PUBLICATION_BLOCKED"):
            service.publish_replacement(**dict(completion, certificate=dict(certified["certificate"], end_offset=1)))
        assert service.publish_replacement(**completion) == replacement["generation_id"]
        assert service.get_operation(operation_id) == journal
        assert published_pointer() == (replacement["generation_id"],)
    else:
        journal = service.get_operation(operation_id)
        with history_error("MIRROR_HISTORY_INVALID"):
            service.publish_replacement(**completion)
        assert published_pointer() == (original["generation_id"],)
        assert service.get_operation(operation_id) == journal
        if receipt_case == "pending":
            with factory() as session:
                assert session.get(HistoryInvalidationRow, operation_id).status == "pending"
        if receipt_case == "missing-target":
            assert admin.execute("SELECT 1 FROM source_mirror_state.history_invalidations WHERE operation_id = %s",
                                 (operation_id,)).fetchone() is None
            assert admin.execute("SELECT DISTINCT history_epoch FROM source_mirror_state.mirrors").fetchall() == [(EPOCH,)]


def test_management_loss_receipt_fences_old_writes_and_preserves_pins(history_loss, monkeypatch):
    admin, factory, history, target, application, publication, reads = history_loss
    lost = allocation(AFFECTED, "orders")
    retained = allocation(RETAINED, "items")
    unpublished = allocation(AFFECTED, "orders")
    for request in (lost, retained, unpublished):
        create_generation(admin, **request)
        delivery(application, request, 0, origin="baseline")
        persist_verified_certificate(admin, **certificate_request(request), verifier=FixtureVerifier())
        if request is not unpublished:
            publication.publish_generation(**certificate_request(request))
            assert delivery(application, request, 1) == {"offset": 1, "commit_seq": 1}
            with factory.begin() as session:
                history.initialize_gate(session, mirror_id=request["mirror_id"], history_epoch=EPOCH)

    read_identity = dict(mirror_id=AFFECTED, execution_user_id="reader")
    pinned = reads.acquire_pin(run_id="old-run", **read_identity)
    retained_pin = reads.acquire_pin(run_id="retained-run", mirror_id=RETAINED, execution_user_id="reader")
    assert reads.read_page(pin=pinned, execution_user_id="reader", after_key=None, limit=10)["freshness"] == "unknown"
    old = history.capture_bound(**read_identity)
    changes = begin_invalidation(history, factory, operation_id="loss")
    new_epoch = changes[0]["history_epoch"]
    original = target.invalidate

    def lose_reply(**kwargs):
        assert original(**kwargs) is True
        raise MirrorError("MIRROR_READ_UNAVAILABLE", 503)

    with monkeypatch.context() as patch:
        patch.setattr(target, "invalidate", lose_reply)
        with history_error("MIRROR_READ_UNAVAILABLE"):
            history.consume_invalidation(operation_id="loss")
    with history_error("MIRROR_HISTORY_INVALID"):
        history.capture_bound(**read_identity)
    with pytest.raises(DBAPIError, match="MIRROR_CONTROL_CONFLICT"):
        delivery(application, lost, 2)
    for request in (lost, unpublished):
        with pytest.raises(DBAPIError, match="MIRROR_CONTROL_CONFLICT"):
            delivery(application, request)
        with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
            publication.publish_generation(**certificate_request(request))
    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        with publication.observe_committed(**observation_request(certificate_request(lost), authority=AUTHORITY,
                                                                  epoch=new_epoch)):
            pytest.fail("The excluded lineage was observed as current publication")

    install(admin)
    history.consume_invalidation(operation_id="loss")
    assert begin_invalidation(history, factory, operation_id="loss") == changes
    with history_error("MIRROR_HISTORY_INVALID"):
        target.invalidate(operation_id="loss", transitions=[dict(changes[0], history_epoch="other-epoch")],
                          reason="history_loss")
    with history_error("MIRROR_HISTORY_INVALID"):
        target.invalidate(operation_id="loss", transitions=changes)
    bound = history.capture_bound(**read_identity)
    assert bound["history_epoch"] == new_epoch
    assert bound["lower_bound"] == bound["upper_bound"]
    with history_error("MIRROR_HISTORY_INVALID"):
        history.read_incremental(**read_identity, after=old["lower_bound"], through=old["upper_bound"], limit=10)
    assert reads.acquire_pin(run_id="old-run", **read_identity) == pinned
    assert reads.acquire_pin(run_id="stale-run", **read_identity).generation_id == pinned.generation_id
    page = reads.read_page(pin=pinned, execution_user_id="reader", after_key=None, limit=10)
    assert (page["freshness"], page["rows"]) == ("stale", [{"id": 1}, {"id": 2}])
    retained_page = reads.read_page(pin=retained_pin, execution_user_id="reader", after_key=None, limit=10)
    assert retained_page["freshness"] == "unknown"

    assert delivery(application, retained, 2) == {"offset": 2, "commit_seq": 2}
    retained_bound = history.capture_bound(mirror_id=RETAINED, execution_user_id="reader")
    assert retained_bound["history_epoch"] == EPOCH
    assert retained_bound["upper_bound"]["commit_seq"] == 2

    retention, = begin_invalidation(history, factory, operation_id="retention", reason="retention")
    history.consume_invalidation(operation_id="retention")
    with pytest.raises(DBAPIError, match="MIRROR_CONTROL_CONFLICT"):
        delivery(application, lost, 2)
    with pytest.raises(ValueError, match="PUBLICATION_BLOCKED"):
        persist_verified_certificate(admin, **certificate_request(unpublished), verifier=FixtureVerifier())
    with pytest.raises(ValueError, match="binding|fence"):
        create_generation(admin, **allocation(AFFECTED, "orders", epoch=retention["history_epoch"]))

    revised = replace(AUTHORITY, control_revision=AUTHORITY.control_revision + 1)
    install_authority(admin, mirror_id=AFFECTED, expected_authority=AUTHORITY, authority=revised,
                      exclusion_proof="fixture", verify_exclusion=lambda *_: True)
    with pytest.raises(DBAPIError, match="MIRROR_CONTROL_CONFLICT"):
        delivery(application, dict(lost, authority=revised), 2)
    with pytest.raises(ValueError, match="binding|fence"):
        create_generation(admin, **allocation(AFFECTED, "orders", authority=revised, epoch=retention["history_epoch"]))

    replacement_authority = replace(revised, control_revision=revised.control_revision + 1,
                                    capture_generation="new-capture")
    install_authority(admin, mirror_id=AFFECTED, expected_authority=revised, authority=replacement_authority,
                      exclusion_proof="fixture", verify_exclusion=lambda *_: True)
    replacement = allocation(AFFECTED, "orders", authority=replacement_authority, epoch=retention["history_epoch"])
    assert create_generation(admin, **replacement) == replacement["generation_id"]
    assert create_generation(admin, **replacement) == replacement["generation_id"]
    delivery(application, replacement, 0, origin="baseline")
    persist_verified_certificate(admin, **certificate_request(replacement), verifier=FixtureVerifier())
    assert publication.publish_generation(**certificate_request(replacement)) == replacement["generation_id"]
    assert delivery(application, replacement, 1) == {"offset": 1, "commit_seq": 1}
    history.consume_invalidation(operation_id="loss")
    current = history.capture_bound(**read_identity)
    assert current["history_epoch"] == retention["history_epoch"]
    assert current["upper_bound"]["commit_seq"] == 1
    assert reads.acquire_pin(run_id="old-run", **read_identity) == pinned
    old_page = reads.read_page(pin=pinned, execution_user_id="reader", after_key=None, limit=10)
    assert (old_page["freshness"], old_page["rows"]) == ("stale", [{"id": 1}, {"id": 2}])
    replacement_pin = reads.acquire_pin(run_id="replacement-run", **read_identity)
    assert replacement_pin.generation_id == replacement["generation_id"]
    replacement_page = reads.read_page(pin=replacement_pin, execution_user_id="reader", after_key=None, limit=10)
    assert replacement_page["freshness"] == "unknown"


def test_loss_serializes_with_coverage_and_blocks_empty_seal(history_loss, monkeypatch):
    admin, factory, history, target, application, _, _ = history_loss
    affected = allocation(AFFECTED, "orders")
    retained = allocation(RETAINED, "items")
    profile = AnchoredProfile(leader_epoch=1)
    for request in (affected, retained):
        create_generation(admin, **request)
        admin.execute("UPDATE source_mirror_state.generations SET anchored_profile = %s WHERE id = %s",
                      (Jsonb(asdict(profile)), request["generation_id"]))
    admin.execute("GRANT EXECUTE ON FUNCTION source_mirror_state.apply_batch(jsonb,text,jsonb,jsonb,jsonb,jsonb) "
                  "TO refraq_mirror_applier")
    with factory.begin() as session:
        history.initialize_gate(session, mirror_id=AFFECTED, history_epoch=EPOCH)
    begin_invalidation(history, factory, operation_id="loss")
    bounds = ReadCommittedBounds(low=0, stable=1, high=1, leader_epoch=profile.leader_epoch)
    scan = SealedScan(start=0, end=1, before=bounds, after=bounds, offsets=(), eof=1)

    with application.engine.begin() as connection:
        coverage = connection.exec_driver_sql("SELECT source_mirror_state.apply_batch(%s, %s, %s, %s, %s, %s)", (
            Jsonb(asdict(AUTHORITY)), affected["generation_id"], Jsonb(asdict(affected["partition_identity"])),
            Jsonb([]), Jsonb(asdict(profile)), Jsonb(asdict(scan)),
        )).scalar_one()
        assert coverage == {"offset": 0, "commit_seq": 0}
        with monkeypatch.context() as patch, history_error("MIRROR_READ_UNAVAILABLE"):
            patch.setattr(target, "timeout_ms", 100)
            history.consume_invalidation(operation_id="loss")

    history.consume_invalidation(operation_id="loss")
    for request in (affected, retained):
        identity = {key: request[key] for key in ("authority", "generation_id", "partition_identity")}
        if request is affected:
            with pytest.raises(DBAPIError, match="MIRROR_CONTROL_CONFLICT"):
                application.apply_batch(**identity, records=[], anchored_profile=profile, scan=scan)
        else:
            assert application.apply_batch(**identity, records=[], anchored_profile=profile, scan=scan) == coverage


@pytest.mark.parametrize("legacy_receipt", ["absent", "pending", "applied"])
def test_legacy_target_loss_requires_fenced_receipt(history_loss, legacy_receipt):
    admin, factory, history, target, application, _, _ = history_loss
    request = allocation(AFFECTED, "orders")
    create_generation(admin, **request)
    with factory.begin() as session:
        history.initialize_gate(session, mirror_id=AFFECTED, history_epoch=EPOCH)
    changes = begin_invalidation(history, factory, operation_id="legacy")
    if legacy_receipt == "absent":
        if admin.execute("SELECT to_regprocedure('source_mirror_state.invalidate_lost_history(text,jsonb,boolean)')"
                         ).fetchone()[0] is not None:
            admin.execute("ALTER FUNCTION source_mirror_state.invalidate_lost_history(text,jsonb,boolean) "
                          "RENAME TO unavailable_in_legacy_target")
        with history_error("MIRROR_READ_UNAVAILABLE"):
            history.consume_invalidation(operation_id="legacy")
        assert target.capture_bound(mirror_id=AFFECTED)["history_epoch"] == EPOCH
        admin.execute("ALTER FUNCTION source_mirror_state.unavailable_in_legacy_target(text,jsonb,boolean) "
                      "RENAME TO invalidate_lost_history")
    else:
        assert target.invalidate(operation_id="legacy", transitions=changes) is True
        if legacy_receipt == "applied":
            with factory.begin() as session:
                session.get(HistoryInvalidationRow, "legacy").status = "applied"
                session.get(HistoryGateRow, AFFECTED).status = "available"
        with history_error("MIRROR_HISTORY_INVALID"):
            history.consume_invalidation(operation_id="legacy")

    with factory() as session:
        receipt = session.get(HistoryInvalidationRow, "legacy")
        assert (receipt.reason, receipt.transitions) == ("history_loss", changes)
        assert receipt.status == ("applied" if legacy_receipt == "applied" else "pending")
        assert session.get(HistoryGateRow, AFFECTED).status == (
            "available" if legacy_receipt == "applied" else "invalidating"
        )
    if legacy_receipt == "absent":
        history.consume_invalidation(operation_id="legacy")
        with pytest.raises(DBAPIError, match="MIRROR_CONTROL_CONFLICT"):
            delivery(application, request)


def test_retention_replays_legacy_target_receipt_and_keeps_same_lineage_writable(history_loss, monkeypatch):
    admin, factory, history, target, application, publication, _ = history_loss
    request = allocation(AFFECTED, "orders")
    create_generation(admin, **request)
    delivery(application, request, 0, origin="baseline")
    persist_verified_certificate(admin, **certificate_request(request), verifier=FixtureVerifier())
    publication.publish_generation(**certificate_request(request))
    with factory.begin() as session:
        history.initialize_gate(session, mirror_id=AFFECTED, history_epoch=EPOCH)
    changes = begin_invalidation(history, factory, operation_id="retention", reason="retention")
    assert target.invalidate(operation_id="retention", transitions=changes) is True
    history.consume_invalidation(operation_id="retention")
    monkeypatch.setattr(target, "invalidate", lambda **kwargs: pytest.fail("Applied retention called the target"))
    history.consume_invalidation(operation_id="retention")
    assert delivery(application, request, 1) == {"offset": 1, "commit_seq": 1}
