"""History loss receipts and the restricted target write boundary on PostgreSQL."""

from dataclasses import asdict, replace
from secrets import token_urlsafe
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from backend.channel.nodes.read.mirror import NODE_TYPE
from backend.core.time import utc_now
from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.bootstrap import create_generation, install, install_authority
from backend.metadata.mirrors.history import History, SqlHistoryTarget
from backend.metadata.mirrors.history_models import HistoryGateRow, HistoryInvalidationRow
from backend.metadata.mirrors.models import MirrorRow
from backend.metadata.mirrors.publication import Publication, persist_verified_certificate
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.service import MirrorError
from backend.metadata.mirrors.types import AnchoredProfile, Authority, PartitionIdentity, ReadCommittedBounds, Record, SealedScan
from backend.metadata.models import SourceRow
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
    for model in (SourceRow, MirrorRow, HistoryGateRow, HistoryInvalidationRow):
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

    def read_mirror_page(*, object_id, after_key, limit):
        assert object_id == "orders"
        return reads.read_page(pin=pinned, execution_user_id="reader", after_key=after_key, limit=limit)

    result = NODE_TYPE.execute({"config": {"object_id": "orders", "freshness_policy": "skip"}},
                               SimpleNamespace(read_mirror_page=read_mirror_page))
    assert result.status == "succeeded"
    assert result.output == dict(rows=[], freshness="stale", source_ids=[AUTHORITY.source_id],
                                 generation_id=pinned.generation_id)
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


def test_retention_replays_legacy_target_receipt_and_keeps_same_lineage_writable(history_loss):
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
    assert delivery(application, request, 1) == {"offset": 1, "commit_seq": 1}
