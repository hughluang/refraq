"""Native PostgreSQL regressions for guarded target publication and run pins."""

from contextlib import nullcontext
from dataclasses import asdict, replace
import os
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.bootstrap import create_generation, install, install_authority
from backend.metadata.mirrors.publication import Publication, persist_verified_certificate
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.service import (
    CommittedOpenPublication, OpenGenerationBinding, OpenPublicationIdentity, publication_certificate_ref,
)
from backend.metadata.mirrors.types import Authority, PartitionIdentity, Record


AUTHORITY = Authority("source", "binding", 3, "runtime", 4, 2, "capture")
MIRROR_ID = "mir_" + "a" * 32


@pytest.fixture
def publication_target():
    dsn = os.getenv("REFRAQ_MIRROR_PUBLICATION_TEST_DSN")
    if not dsn:
        pytest.skip("Set REFRAQ_MIRROR_PUBLICATION_TEST_DSN to a disposable PostgreSQL target")
    database = "publication_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as maintenance:
        maintenance.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(
            dsn, dbname=database, options="-c role=refraq_mirror_applier"))
        try:
            with psycopg.connect(dsn, dbname=database, autocommit=True) as admin:
                install(admin)
                yield admin, Application(engine), Publication(engine)
        finally:
            engine.dispose()
            maintenance.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


class FixtureVerifier:
    def verify(self, *, authority, certificate):
        return "native-publication-retry-fixture"


def prepare_generation(admin, generation_number):
    generation_id = str(generation_number) * 32
    operation_id = f"open-{generation_number}"
    partition = PartitionIdentity("cluster", f"topic-{generation_number}", 0)
    create_generation(
        admin, mirror_id=MIRROR_ID, generation_id=generation_id, authority=AUTHORITY,
        operation_id=operation_id, table_identity="orders", history_epoch="epoch",
        schema_fingerprint="schema", columns={"id": "bigint"}, key_columns=("id",),
        partition_identity=partition, start_offset=-1,
    )
    certificate = dict(
        operation_id=operation_id, generation_id=generation_id, table_identity="orders",
        capture_generation=AUTHORITY.capture_generation, schema_fingerprint="schema",
        partition_identity=asdict(partition), end_offset=0, source_completion="snapshot",
        producer_exclusion="exclusion", durable_source_checkpoint="checkpoint",
        ordered_delivery_proof="coverage", key_fingerprint="key", empty_table_proof=False,
    )
    request = dict(operation_id=operation_id, authority=AUTHORITY,
                   generation_id=generation_id, certificate=certificate)
    persist_verified_certificate(admin, **request, verifier=FixtureVerifier())
    return request


def deliver(application, request, *records):
    return application.apply_batch(
        authority=AUTHORITY, generation_id=request["generation_id"],
        partition_identity=PartitionIdentity(**request["certificate"]["partition_identity"]),
        records=list(records),
    )


def order_record(offset, origin):
    values = {"id": offset + 1}
    return Record(offset, "orders", AUTHORITY.capture_generation, "upsert", origin, values, values)


@pytest.mark.parametrize("superseded", [False, True], ids=["current", "superseded"])
def test_publication_retry_confirms_only_current_generation(publication_target, superseded):
    admin, application, publication = publication_target
    first = prepare_generation(admin, 1)
    assert deliver(application, first, order_record(0, "baseline"))["offset"] == 0
    assert publication.publish_generation(**first) == first["generation_id"]
    assert publication.publish_generation(**first) == first["generation_id"]

    current = first
    if superseded:
        current = prepare_generation(admin, 2)
        assert deliver(application, current, order_record(0, "baseline"))["offset"] == 0
        assert publication.publish_generation(**current) == current["generation_id"]

    progress = deliver(application, current, order_record(1, "live"))
    assert progress == {"offset": 1, "commit_seq": 1}
    if superseded:
        with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
            publication.publish_generation(**first)
    assert publication.publish_generation(**current) == current["generation_id"]
    assert deliver(application, current) == progress


def test_pinned_run_resumes_paging_across_publication_switch(publication_target):
    admin, application, publication = publication_target
    first = prepare_generation(admin, 1)
    deliver(application, first, order_record(0, "baseline"))
    assert publication.publish_generation(**first) == first["generation_id"]
    deliver(application, first, order_record(1, "live"))

    def authorize_fixture_source_read(*, execution_user_id, source_id):
        assert (execution_user_id, source_id) == ("reader", AUTHORITY.source_id)

    gateway = create_engine("postgresql+psycopg://", poolclass=NullPool, creator=lambda: psycopg.connect(
        os.environ["REFRAQ_MIRROR_PUBLICATION_TEST_DSN"], dbname=admin.info.dbname,
        options="-c role=refraq_mirror_gateway",
    ))
    gateway_options = dict(authorize_source_read=authorize_fixture_source_read, verify_terminal_proof=pytest.fail)
    read_identity = dict(mirror_id=MIRROR_ID, execution_user_id="reader")
    reads = Reads(gateway, **gateway_options)
    first_pin = reads.acquire_pin(run_id="original-run", **read_identity)
    assert first_pin.generation_id == first["generation_id"]
    first_page = reads.read_page(pin=first_pin, execution_user_id="reader", after_key=None, limit=1)
    assert (first_page["rows"], first_page["next_key"]) == ([{"id": 1}], {"id": 1})

    replacement = prepare_generation(admin, 2)
    replacement_row = {"id": 3}
    deliver(application, replacement, replace(order_record(0, "baseline"), key=replacement_row, values=replacement_row))
    assert publication.publish_generation(**replacement) == replacement["generation_id"]

    resumed_reads = Reads(gateway, **gateway_options)
    resumed_pin = resumed_reads.acquire_pin(run_id="original-run", **read_identity)
    assert resumed_pin == first_pin
    resumed_page = resumed_reads.read_page(
        pin=resumed_pin, execution_user_id="reader", after_key=first_page["next_key"], limit=2,
    )
    assert (resumed_page["generation_id"], resumed_page["rows"], resumed_page["next_key"]) == (
        first["generation_id"], [{"id": 2}], None,
    )

    fresh_pin = resumed_reads.acquire_pin(run_id="fresh-run", **read_identity)
    assert fresh_pin.generation_id == replacement["generation_id"]
    fresh_page = resumed_reads.read_page(pin=fresh_pin, execution_user_id="reader", after_key=None, limit=2)
    assert fresh_page["rows"] == [{"id": 3}]


@pytest.mark.parametrize("applied_offset", [-1, 1], ids=["behind", "ahead"])
def test_first_publication_requires_exact_applied_boundary(publication_target, applied_offset):
    admin, application, publication = publication_target
    request = prepare_generation(admin, 1)
    if applied_offset == 1:
        deliver(application, request, order_record(0, "baseline"), order_record(1, "baseline"))
    assert deliver(application, request)["offset"] == applied_offset
    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        publication.publish_generation(**request)


def test_publication_retry_requires_exact_certificate_and_current_fence(publication_target):
    admin, application, publication = publication_target
    request = prepare_generation(admin, 1)
    deliver(application, request, order_record(0, "baseline"))
    assert publication.publish_generation(**request) == request["generation_id"]

    changed_certificate = dict(request["certificate"], durable_source_checkpoint="different")
    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        publication.publish_generation(**dict(request, certificate=changed_certificate))

    install_authority(
        admin, mirror_id=MIRROR_ID, expected_authority=AUTHORITY,
        authority=replace(AUTHORITY, control_revision=AUTHORITY.control_revision + 1),
        exclusion_proof="exclusion", verify_exclusion=lambda *_: True,
    )
    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        publication.publish_generation(**request)
    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        with publication.observe_committed(**observation_request(request)):
            pytest.fail("An old publication fence was observed")


@pytest.mark.parametrize("status, certificate_published, applied_offset", [
    pytest.param("retired", True, 0, id="retired-current"),
    pytest.param("catching_up", False, 0, id="unpublished-current"),
    pytest.param("published", True, -1, id="regressed-offset"),
])
def test_publication_retry_rejects_contradictory_target_state(
    publication_target, status, certificate_published, applied_offset,
):
    admin, application, publication = publication_target
    request = prepare_generation(admin, 1)
    deliver(application, request, order_record(0, "baseline"))
    assert publication.publish_generation(**request) == request["generation_id"]

    with admin.transaction():
        admin.execute(
            "UPDATE source_mirror_state.generations SET status = %s, applied_offset = %s WHERE id = %s",
            (status, applied_offset, request["generation_id"]),
        )
        admin.execute(
            "UPDATE source_mirror_state.certificates SET published = %s WHERE operation_id = %s",
            (certificate_published, request["operation_id"]),
        )

    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        publication.publish_generation(**request)
    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        with publication.observe_committed(**observation_request(request)):
            pytest.fail("Contradictory publication state was observed")


def observation_request(request, *, authority=AUTHORITY, epoch="epoch"):
    certificate = request["certificate"]
    return dict(
        mirror_id=MIRROR_ID, operation_id=request["operation_id"],
        binding=OpenGenerationBinding(
            authority=authority, object_id="catalog-orders", table_identity="orders",
            qualified_table="public.orders", history_epoch=epoch, schema_fingerprint="schema",
            columns={"id": "bigint"}, key_columns=("id",), start_offset=-1,
            partition_identity=PartitionIdentity(**certificate["partition_identity"]),
        ),
        expected=OpenPublicationIdentity(
            authority=authority, generation_id=request["generation_id"], history_epoch=epoch,
            snapshot_operation_id="snapshot", scan_offset=3, completion_offset=4,
            certificate_ref=publication_certificate_ref(certificate),
        ),
    )


def publish_in_transaction(admin, request):
    admin.execute("SET LOCAL ROLE refraq_mirror_applier")
    return admin.execute("SELECT source_mirror_state.publish_generation(%s, %s, %s, %s)", (
        request["operation_id"], Jsonb(asdict(request["authority"])), request["generation_id"],
        Jsonb(request["certificate"]),
    )).fetchone()[0]


def test_observer_requires_committed_publication_and_returns_current_target_view(publication_target):
    admin, application, publication = publication_target
    request = prepare_generation(admin, 1)
    deliver(application, request, order_record(0, "baseline"))
    observe = observation_request(request)
    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        with publication.observe_committed(**observe):
            pytest.fail("An unpublished certificate was observed")

    observer = Publication(publication.engine, timeout_ms=150)
    with admin.transaction():
        assert publish_in_transaction(admin, request) == request["generation_id"]
        with pytest.raises(DBAPIError) as blocked:
            with observer.observe_committed(**observe):
                pytest.fail("An uncommitted publication was observed")
        assert blocked.value.orig.sqlstate in {"55P03", "57014"}

    deliver(application, request, order_record(1, "live"))
    with publication.observe_committed(**observe) as observed:
        assert isinstance(observed, CommittedOpenPublication)
        assert observed.published_generation_id == request["generation_id"]
        assert observed.applied_offset == 1
        assert observed.certificate == dict(
            operation_id=request["operation_id"], generation_id=request["generation_id"],
            authority=asdict(AUTHORITY), evidence=request["certificate"],
            verified_by="native-publication-retry-fixture", published=True,
        )
        assert observed.allocation == dict(
            generation_id=request["generation_id"], authority=asdict(AUTHORITY), table_identity="orders",
            mirror_id=MIRROR_ID, operation_id=request["operation_id"], history_epoch="epoch",
            fence_receipt=None, start_offset=-1, capture_generation="capture", schema_fingerprint="schema",
            key_columns=["id"], column_names=["id"], partition_identity=request["certificate"]["partition_identity"],
            cleanup_pending=False, status="published", native_types={"id": "bigint"},
        )
        assert observed.history_bound == dict(
            mirror_id=MIRROR_ID, source_id="source", history_epoch="epoch",
            lower_bound=dict(mirror_id=MIRROR_ID, history_epoch="epoch", commit_seq=0, entry_seq=0),
            upper_bound=dict(mirror_id=MIRROR_ID, history_epoch="epoch", commit_seq=1, entry_seq=1),
        )


@pytest.mark.parametrize("caller_failed", [False, True], ids=["commit", "rollback"])
def test_observer_guards_pointer_until_context_exit(publication_target, caller_failed):
    admin, application, publication = publication_target
    first, successor = [prepare_generation(admin, number) for number in (1, 2)]
    for request in (first, successor):
        deliver(application, request, order_record(0, "baseline"))
    publication.publish_generation(**first)

    disposition = pytest.raises(RuntimeError, match="caller failed") if caller_failed else nullcontext()
    observe = observation_request(first)
    with disposition, publication.observe_committed(**observe):
        with publication.observe_committed(**observe) as concurrent:
            assert concurrent.published_generation_id == first["generation_id"]
        with pytest.raises(psycopg.errors.LockNotAvailable), admin.transaction():
            admin.execute("SET LOCAL lock_timeout = '150ms'")
            publish_in_transaction(admin, successor)
        if caller_failed:
            raise RuntimeError("caller failed")

    assert publication.publish_generation(**successor) == successor["generation_id"]
    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        with publication.observe_committed(**observation_request(first)):
            pytest.fail("The superseded generation was observed")


@pytest.mark.parametrize("mismatch", ["mirror_id", "operation_id", "generation_id", "authority", "history_epoch"])
def test_observer_rejects_mismatched_target_identity(publication_target, mismatch):
    admin, application, publication = publication_target
    request = prepare_generation(admin, 1)
    deliver(application, request, order_record(0, "baseline"))
    publication.publish_generation(**request)
    if mismatch == "authority":
        observe = observation_request(request, authority=replace(AUTHORITY, credential_revision=3))
    elif mismatch == "history_epoch":
        observe = observation_request(request, epoch="other-epoch")
    else:
        observe = observation_request(request)
        if mismatch == "generation_id":
            observe["expected"] = replace(observe["expected"], generation_id="2" * 32)
        else:
            observe[mismatch] = "other-id"

    with pytest.raises(DBAPIError, match="MIRROR_PUBLICATION_BLOCKED"):
        with publication.observe_committed(**observe):
            pytest.fail("A mismatched publication was observed")


def test_observer_role_boundary_and_reinstall(publication_target):
    admin, application, publication = publication_target
    request = prepare_generation(admin, 1)
    deliver(application, request, order_record(0, "baseline"))
    publication.publish_generation(**request)
    observe = observation_request(request)
    for role in ("refraq_mirror_gateway", "pg_monitor"):
        assert admin.execute("SELECT has_function_privilege(%s, "
                             "'source_mirror_state.observe_committed_publication(text,text,text,jsonb,text)', "
                             "'EXECUTE')", (role,)).fetchone() == (False,)
    for table in ("mirrors", "generations", "certificates", "live_log"):
        with pytest.raises(DBAPIError) as denied, publication.engine.begin() as connection:
            connection.execute(text(f"SELECT 1 FROM source_mirror_state.{table}"))
        assert denied.value.orig.sqlstate == "42501"

    admin.execute("DROP FUNCTION source_mirror_state.observe_committed_publication(text,text,text,jsonb,text)")
    with pytest.raises(DBAPIError) as missing:
        with publication.observe_committed(**observe):
            pytest.fail("A missing observer allowed publication")
    assert missing.value.orig.sqlstate == "42883"
    install(admin)
    install(admin)
    with publication.observe_committed(**observe) as observed:
        assert observed.published_generation_id == request["generation_id"]


def test_logical_json_preserves_numeric_and_null_identity_through_delivery(publication_target):
    import json
    from copy import deepcopy
    from backend.metadata.capture.test_delivery import SCHEMA, decoder, envelope, wire_key

    admin, application, _ = publication_target
    generation = "a" * 32
    partition = PartitionIdentity("cluster", "topic-json", 0)
    table = sql.Identifier("source_mirror", "m_" + MIRROR_ID[4:20] + "_" + generation)
    create_generation(
        admin, mirror_id=MIRROR_ID, generation_id=generation, authority=AUTHORITY,
        operation_id="json-open", table_identity="table", history_epoch="epoch",
        schema_fingerprint="schema", columns={"id": "integer", "body": "jsonb"},
        key_columns=("id",), partition_identity=partition, start_offset=-1,
    )
    schema = deepcopy(SCHEMA)
    for side in schema["fields"][:2]:
        side["fields"][1]["name"] = "io.debezium.data.Json"
    capture = decoder(value_schema=schema)
    precise = '{"n":12345678901234567890.12345}'
    target_query = sql.SQL("SELECT body IS NULL, jsonb_typeof(body), body->>'n' FROM {}").format(table)
    for offset, (body, expected, sequence) in enumerate([
        (precise, (False, "object", "12345678901234567890.12345"), 1),
        (None, (True, None, None), 2),
        ("null", (False, "null", None), 3),
        ("__debezium_unavailable_value", (False, "null", None), 3),
        (None, (True, None, None), 4),
    ]):
        message = envelope(op="u" if offset else "c", body=body)
        if offset:
            message["payload"]["before"]["body"] = None
        message["schema"] = schema
        record = capture.decode(offset=offset, key=wire_key(), value=json.dumps(message).encode())
        for _ in range(2):
            coverage = application.apply_batch(
                authority=AUTHORITY, generation_id=generation, partition_identity=partition, records=[record],
            )
            assert admin.execute(target_query).fetchone() == expected
            assert coverage == {"offset": offset, "commit_seq": sequence}
    history = admin.execute(
        "SELECT before_image->'body'->>'n', after_image->'body'->>'n', "
        "before_json_null_columns, after_json_null_columns FROM source_mirror_state.live_log ORDER BY commit_seq"
    ).fetchall()
    assert history == [(None, "12345678901234567890.12345", None, []),
                       ("12345678901234567890.12345", None, [], []),
                       (None, None, [], ["body"]), (None, None, ["body"], [])]


def test_legacy_target_marker_upgrade_retains_history(publication_target):
    admin, application, _ = publication_target
    request = prepare_generation(admin, 1)
    row = Record(0, "orders", AUTHORITY.capture_generation, "upsert", "live", {"id": 1}, {"id": 1})
    deliver(application, request, row)
    with admin.transaction():
        admin.execute("ALTER TABLE source_mirror_state.live_log DROP COLUMN before_json_null_columns, DROP COLUMN after_json_null_columns")
        admin.execute("UPDATE source_mirror_state.version SET version = 1")
    install(admin)
    install(admin)
    assert admin.execute("SELECT source_mirror_state.target_version()").fetchone() == (2,)
    assert admin.execute("SELECT after_image, after_json_null_columns FROM source_mirror_state.live_log").fetchone() == ({"id": 1}, None)
    assert deliver(application, request, row) == {"offset": 0, "commit_seq": 1}


def test_json_literal_null_key_pages_in_native_order(publication_target):
    admin, application, _ = publication_target
    generation = "c" * 32
    partition = PartitionIdentity("cluster", "json-keys", 0)
    create_generation(
        admin, mirror_id=MIRROR_ID, generation_id=generation, authority=AUTHORITY,
        operation_id="json-keys-open", table_identity="table", history_epoch="epoch",
        schema_fingerprint="schema", columns={"id": "jsonb"}, key_columns=("id",),
        partition_identity=partition, start_offset=-1,
    )
    records = [Record(0, "table", "capture", "upsert", "live", {"id": None}, {"id": None},
                      json_null_columns=("id",)),
               Record(1, "table", "capture", "upsert", "live", {"id": "next"}, {"id": "next"})]
    application.apply_batch(authority=AUTHORITY, generation_id=generation, partition_identity=partition, records=records)
    admin.execute("INSERT INTO source_mirror_state.reader_pins VALUES ('reader', %s, %s)", (MIRROR_ID, generation))
    page_sql = "SELECT source_mirror_state.read_page('reader', %s, %s, 1)"
    first = admin.execute(page_sql, (MIRROR_ID, None)).fetchone()[0]
    assert first["rows"] == [{"id": None}]
    second = admin.execute(page_sql, (MIRROR_ID, Jsonb(first["next_key"]))).fetchone()[0]
    assert second["rows"] == [{"id": "next"}]
