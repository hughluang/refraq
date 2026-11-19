"""Native PostgreSQL regression for guarded target publication retries."""

from dataclasses import asdict, replace
import os
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError

from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.bootstrap import create_generation, install, install_authority
from backend.metadata.mirrors.publication import Publication, persist_verified_certificate
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
