"""Confirmed Channel publication through the guarded PostgreSQL Mirror target."""

from contextlib import ExitStack, closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from backend.admin.errors import AuthForbidden
from backend.admin.models import (
    AuditEventRow,
    RoleRow,
    SystemParameterRow,
    UserGroupMemberRow,
    UserGroupRow,
    UserRow,
)
from backend.admin.system_parameters import registry as parameter_registry
from backend.admin.system_parameters import reset_parameter_store
from backend.channel import mirror_reads
from backend.channel import service as channels
from backend.channel.channel_run import mint_on_demand_run
from backend.channel.errors import ChannelRequestInvalid
from backend.channel.models import (
    ChannelDatasetRow,
    ChannelNodeExecutionRow,
    ChannelRow,
    ChannelRunRow,
    ChannelVersionRow,
    InboundPathRow,
)
from backend.channel.run_store import get_run_store
from backend.channel.schemas.channels import TableSetupIn
from backend.channel.runner import run_channel_job
from backend.core import db
from backend.core.config import reset_settings_cache
from backend.core.secrets import encrypt_secret
from backend.core.time import utc_now
from backend.jobs.models import JobRow
from backend.jobs.store import get_job_store
from backend.metadata.capture import control
from backend.metadata.capture.runtime import CaptureRuntime
from backend.metadata.capture.runtime_store import CommandJournal, RuntimeBlocked
from backend.metadata.mirrors import bootstrap, history
from backend.metadata.mirrors import service as mirrors
from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.authorization import authorize_source_data
from backend.metadata.mirrors.history_models import HistoryGateRow
from backend.metadata.mirrors.models import (
    MirrorIntentReceiptRow,
    MirrorOperationRow,
    MirrorPublicationRow,
    MirrorReferenceRow,
    MirrorRow,
)
from backend.metadata.mirrors.publication import (
    Publication,
    persist_verified_certificate,
)
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.types import Authority, PartitionIdentity, Record
from backend.metadata.models import (
    CatalogObjectRow,
    SourceCaptureBindingRow,
    SourceCaptureOperationRow,
    SourceMembershipRow,
    SourceRow,
)
from backend.metadata.source_access import (
    authorize_source_read_on,
    create_membership,
    delete_membership,
    reset_source_access_store,
)
from backend.metadata.sources.store import SourceRecord, get_source_store
from backend.tags.models import TagAssignmentRow, TagRow, TagSubjectRevisionRow
from backend.tags.store import reset_tag_store
from backend.tests.test_capture_preparation import (
    management_engine as management_engine,
    native_target as native_target,
)
from backend.tests.test_channel_api_pg import TRIGGER
from backend.tests.test_mirror_generation_allocation import target_dsn as target_dsn
from backend.worker.models import ScheduledTaskRow
from backend.worker.parameters import assemble_system_parameters


SOURCE = "publication-source"
PUBLISHER = "channel-publisher"
READER = "channel-reader"


@pytest.fixture
def channel_management(management_engine, monkeypatch, request):
    monkeypatch.setenv("REFRAQ_STORE_BACKEND", "persistent")
    monkeypatch.setenv("REFRAQ_SECRETS_MASTER_KEY", "disposable-publication-fixture")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://fixture/management?sslmode=verify-full"
    )
    monkeypatch.setenv("REDIS_URL", "redis://fixture/0")
    reset_settings_cache()
    request.addfinalizer(reset_settings_cache)
    reset_source_access_store()
    request.addfinalizer(reset_source_access_store)
    reset_tag_store()
    request.addfinalizer(reset_tag_store)
    models = (
        AuditEventRow,
        RoleRow,
        SystemParameterRow,
        UserRow,
        UserGroupRow,
        UserGroupMemberRow,
        JobRow,
        SourceRow,
        CatalogObjectRow,
        SourceMembershipRow,
        SourceCaptureBindingRow,
        SourceCaptureOperationRow,
        MirrorRow,
        MirrorReferenceRow,
        MirrorOperationRow,
        MirrorPublicationRow,
        MirrorIntentReceiptRow,
        HistoryGateRow,
        ChannelRow,
        ChannelVersionRow,
        InboundPathRow,
        ChannelRunRow,
        ChannelNodeExecutionRow,
        ChannelDatasetRow,
        ScheduledTaskRow,
        TagRow,
        TagAssignmentRow,
        TagSubjectRevisionRow,
    )
    db.Base.metadata.create_all(
        management_engine, tables=[model.__table__ for model in models]
    )
    sessions = sessionmaker(management_engine, autoflush=False)
    monkeypatch.setattr(db, "get_session_factory", lambda: sessions)
    reset_parameter_store()
    request.addfinalizer(reset_parameter_store)
    monkeypatch.setattr(parameter_registry, "_registry", {})
    monkeypatch.setattr(parameter_registry, "_group_order", ())
    monkeypatch.setattr(parameter_registry, "_frozen", False)
    assemble_system_parameters()
    monkeypatch.setattr(mirrors, "_store", None)
    monkeypatch.setattr(mirrors, "_source_read_authorizer", authorize_source_read_on)
    now = utc_now()
    with sessions.begin() as session:
        assert session.get(SystemParameterRow, "schedule_timezone") is not None
        session.add_all(
            [
                RoleRow(
                    id="publisher-role",
                    key="publisher",
                    name="Publisher",
                    permissions=["channel:write", "sources:data_read"],
                    created_at=now.timestamp(),
                ),
                RoleRow(
                    id="reader-role",
                    key="reader",
                    name="Reader",
                    permissions=["sources:data_read"],
                    created_at=now.timestamp(),
                ),
            ]
        )
        session.flush()
        session.add_all(
            UserRow(
                id=user,
                role_id=role_id,
                account=user,
                display_name=user,
                created_at=now,
            )
            for user, role_id in (
                (PUBLISHER, "publisher-role"),
                (READER, "reader-role"),
            )
        )
        source = get_source_store().create_source_on(
            session,
            SourceRecord(
                id=SOURCE,
                key="publication",
                locator_key="fixture-db",
                name="Publication",
                kind="database",
                status="active",
                engine="postgresql",
                description=None,
                access_ciphertext=None,
                access_updated_at=None,
                capture_credential_ciphertext=encrypt_secret(
                    '{"username":"capture","password":"fixture"}'
                ),
                capture_revision=1,
                created_at=now,
                updated_at=now,
            ),
        )
        control.record_source_intent(
            session, None, source, actor_user_id=PUBLISHER, actor_token_id=None
        )
        session.add(
            CatalogObjectRow(
                id="items",
                source_id=SOURCE,
                locator_key="fixture-items",
                object_type="table",
                schema_name="public",
                name="items",
                created_at=now,
                updated_at=now,
            )
        )
        session.add_all(
            SourceMembershipRow(
                id=user,
                subject_type="user",
                subject_id=user,
                target=SOURCE,
                level="viewer",
                created_at=now,
                updated_at=now,
            )
            for user in (PUBLISHER, READER)
        )
    return sessions


@pytest.fixture
def restricted_target(native_target, channel_management, monkeypatch):
    def engine(role):
        password = uuid4().hex
        with psycopg.connect(native_target) as admin:
            admin.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        return create_engine(
            "postgresql+psycopg://",
            poolclass=NullPool,
            creator=lambda: psycopg.connect(
                native_target,
                user=role,
                password=password,
                options="-c lock_timeout=3000 -c statement_timeout=3000",
                connect_timeout=3,
            ),
        )

    with ExitStack() as resources:
        applier = engine("refraq_mirror_applier")
        gateway = engine("refraq_mirror_gateway")
        resources.callback(applier.dispose)
        resources.callback(gateway.dispose)
        for serving_engine, role in (
            (applier, "refraq_mirror_applier"),
            (gateway, "refraq_mirror_gateway"),
        ):
            with serving_engine.connect() as connection:
                bootstrap.validate_target(
                    connection.connection.driver_connection, expected_role=role
                )
        monkeypatch.setattr(mirror_reads, "_reads", None)
        mirror_reads.bind_reads(
            Reads(
                gateway,
                authorize_source_read=authorize_source_data,
                verify_terminal_proof=mirror_reads.validate_terminal_proof,
            )
        )
        monkeypatch.setattr(history, "_history", None)
        history.bind_history(
            session_factory=channel_management,
            target=history.SqlHistoryTarget(
                engine=gateway,
                invalidation_engine=applier,
                timeout_ms=3000,
            ),
        )
        yield applier


def prepare_open(sessions, dsn, mirror, operation_id):
    """Inject applied owner and snapshot evidence from the native test boundary."""
    mirror_id = mirror["id"]
    with sessions.begin() as session:
        state = control.load_binding(session, SOURCE)
        authority = Authority(
            SOURCE,
            state["binding_id"],
            1,
            "fixture-owner",
            state["control_revision"],
            state["credential_revision"],
            str(state["capture_generation"]),
        )
        state.update(
            owner_epoch=authority.owner_epoch,
            runtime_instance_id=authority.runtime_instance_id,
            applied_revision=authority.control_revision,
        )
        control.save_binding(session, state)

    binding = mirrors.OpenGenerationBinding(
        authority=authority,
        object_id="items",
        table_identity=mirror["table_identity"],
        qualified_table="public.items",
        history_epoch=mirrors.initial_history_epoch(mirror_id),
        schema_fingerprint="fixture-items-schema",
        columns={"id": "bigint", "value": "text"},
        key_columns=("id",),
        partition_identity=PartitionIdentity(
            "fixture-cluster", "fixture-items-topic", 0
        ),
        start_offset=-1,
    )
    with psycopg.connect(dsn) as connection:
        receipt = bootstrap.prepare_authority(
            connection,
            mirror_id=mirror_id,
            table_identity=binding.table_identity,
            history_epoch=binding.history_epoch,
            operation_id="fixture-fence",
            expected_authority=None,
            authority=authority,
            exclusion_proof=authority,
            verify_exclusion=lambda previous, current, proof: (
                previous is None and current == proof
            ),
        )

    def allocate(**request):
        with psycopg.connect(dsn) as connection:
            return bootstrap.create_generation(connection, **request)

    allocation_request = dict(
        binding=binding,
        mirror_id=mirror_id,
        operation_id=operation_id,
        mirror_revision=mirror["control"]["control_revision"],
    )
    generation_id = mirrors.reconcile_open_generation(
        mirror_id=mirror_id,
        operation_id=operation_id,
        binding=binding,
        allocate=allocate,
        verify_binding=lambda **request: request == allocation_request,
    )
    snapshot_id = "fixture-snapshot-signal"
    snapshot_binding = dict(
        authority=asdict(authority),
        mirror_id=mirror_id,
        mirror_revision=mirror["control"]["control_revision"],
        allocation_operation_id=operation_id,
        generation_id=generation_id,
        table_identity=binding.table_identity,
        qualified_table=binding.qualified_table,
        history_epoch=binding.history_epoch,
        schema_fingerprint=binding.schema_fingerprint,
        data_partition=asdict(binding.partition_identity),
        notification_topic="fixture-notifications",
        notification_partition=0,
    )
    snapshot = dict(
        id=snapshot_id,
        state="catching_up",
        receipt=True,
        binding=snapshot_binding,
        scan={"offset": 11},
        completion={"offset": 12},
    )
    with sessions.begin() as session:
        control.save_binding(
            session,
            dict(
                control.load_binding(session, SOURCE),
                incremental_snapshots={"generations": {generation_id: snapshot}},
            ),
        )
    source_completion = dict(
        operation=snapshot_id,
        table=binding.qualified_table,
        notification_topic="fixture-notifications",
        notification_partition=0,
        terminals=[
            {
                "offset": 11,
                "event": {"id": snapshot_id, "type": "TABLE_SCAN_COMPLETED"},
            },
            {"offset": 12, "event": {"id": snapshot_id, "type": "COMPLETED"}},
        ],
    )
    certificate = dict(
        operation_id=operation_id,
        generation_id=generation_id,
        table_identity=binding.table_identity,
        capture_generation=authority.capture_generation,
        schema_fingerprint=binding.schema_fingerprint,
        partition_identity=asdict(binding.partition_identity),
        end_offset=1,
        source_completion=source_completion,
        producer_exclusion=receipt,
        durable_source_checkpoint="fixture-source-checkpoint",
        ordered_delivery_proof="fixture-seal-[0,2)",
        key_fingerprint="fixture-bigint-key",
        empty_table_proof=False,
    )
    expected = mirrors.OpenPublicationIdentity(
        authority=authority,
        generation_id=generation_id,
        history_epoch=binding.history_epoch,
        snapshot_operation_id=snapshot_id,
        scan_offset=11,
        completion_offset=12,
        certificate_ref=mirrors.publication_certificate_ref(certificate),
    )
    return binding, expected, certificate


class FixtureCertificateVerifier:
    """Admit only the fixture certificate whose native evidence is supplied by the test."""

    def __init__(self, authority, certificate_ref):
        self.authority = authority
        self.certificate_ref = certificate_ref

    def verify(self, *, authority, certificate):
        assert authority == self.authority
        assert mirrors.publication_certificate_ref(certificate) == self.certificate_ref
        return "disposable-channel-fixture"


@pytest.mark.integration
def test_concurrent_table_setup_records_one_creation(channel_management):
    with channel_management.begin() as session:
        role = session.get(RoleRow, "publisher-role")
        role.permissions = [*role.permissions, "metadata:read"]

    setup = TableSetupIn(object_id="items", request_id=uuid4())
    def create():
        return channels.create_channel(name="Items", description=None, actor_user_id=PUBLISHER,
                                       actor_token_id=None, table_setup=setup, names=["Items"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(create) for _ in range(2)]
        first, replay = [request.result() for request in requests]
    assert replay.id == first.id
    with channel_management() as session:
        actions = session.scalars(select(AuditEventRow.action).where(AuditEventRow.resource_id == first.id)).all()
        assert sorted(actions) == ["channel.create", "tags.replace"]


@pytest.mark.integration
def test_confirmed_channel_open_rechecks_grants_and_keeps_pin_across_switch(
    channel_management, native_target, restricted_target, tmp_path
):
    actor = dict(actor_user_id=PUBLISHER, actor_token_id=None)
    channel = channels.create_channel(name="Published items", description=None, **actor)
    read_node = dict(
        TRIGGER["nodes"][0],
        id="nd_items",
        ref="items",
        type="read.mirror",
        name="Items",
        config={"object_id": "items", "freshness_policy": "continue"},
    )
    edge = {
        "id": "ed_items",
        "source": {"node_id": "nd_trigger", "port": "main"},
        "target": {"node_id": "nd_items", "port": "main"},
    }
    graph = dict(TRIGGER, nodes=[*TRIGGER["nodes"], read_node], edges=[edge])
    draft = channels.save_draft(
        channel_id=channel.id,
        base_revision=channel.draft_revision,
        graph=graph,
        **actor,
    )
    publish = dict(channel_id=channel.id, draft_revision=draft.draft_revision, **actor)
    confirmed = channels.preview_publish(channel.id, PUBLISHER)["mirrors_to_open"]
    (opening,) = confirmed
    mirror_id = opening["mirror_id"]
    assert opening == dict(source_id=SOURCE, object_id="items", mirror_id=mirror_id)
    receipt_id = f"channel:{channel.id}:1"

    def assert_no_publication():
        with channel_management() as session:
            assert session.get(ChannelVersionRow, (channel.id, 1)) is None
            assert session.get(MirrorReferenceRow, (channel.id, mirror_id)) is None
            assert session.get(MirrorRow, mirror_id) is None
            assert session.get(MirrorIntentReceiptRow, receipt_id) is None
            operation_id = session.scalar(
                select(MirrorOperationRow.id).where(
                    MirrorOperationRow.mirror_id == mirror_id
                )
            )
            assert operation_id is None
            publish_audit_id = session.scalar(
                select(AuditEventRow.id).where(
                    AuditEventRow.resource_id == channel.id,
                    AuditEventRow.action == "channel.publish",
                )
            )
            assert publish_audit_id is None

    assert_no_publication()
    with pytest.raises(ChannelRequestInvalid, match="explicit open confirmation"):
        channels.publish_channel(**publish)
    assert_no_publication()
    with pytest.raises(mirrors.MirrorError) as rejected:
        channels.publish_channel(**publish, mirrors_to_open=[])
    assert rejected.value.code == "MIRROR_CONTROL_CONFLICT"
    assert_no_publication()

    version, confirmation = channels.publish_channel(
        **publish, mirrors_to_open=confirmed
    )
    assert version.number == 1
    assert confirmation["mirrors_to_open"] == confirmed
    assert confirmation["mirror_bindings"][0]["effect"] == "first_open"
    table, = channels.version_mirror_bindings(PUBLISHER, version)
    assert (table["effect"], table["publication_effect"]) == ("shared", "first_open")
    assert channels.get_version(channel.id, 1).graph == graph
    with channel_management() as session:
        ref = session.get(MirrorReferenceRow, (channel.id, mirror_id))
        assert ref.channel_version == version.number
        receipt = session.get(MirrorIntentReceiptRow, receipt_id)
        assert receipt.request["confirmed_mirrors_to_open"] == confirmed
    pending = mirrors.get_mirror(mirror_id)
    (opened,) = pending["operations"]
    assert (opened["kind"], opened["state"]) == ("open", "pending")
    assert pending["published_reference_count"] == 1
    assert pending["published_generation_id"] is pending["history_epoch"] is None

    control.reconcile_published_scope(SOURCE)
    binding, expected, certificate = prepare_open(
        channel_management, native_target, pending, opened["id"]
    )
    generation_id = expected.generation_id
    target = Application(restricted_target)
    delivery = dict(
        authority=binding.authority,
        generation_id=generation_id,
        partition_identity=binding.partition_identity,
    )
    first = {"id": 1, "value": "first"}
    second = {"id": 2, "value": "second"}
    assert target.apply_batch(
        **delivery,
        records=[
            Record(
                offset,
                binding.table_identity,
                binding.authority.capture_generation,
                "upsert",
                "baseline",
                {"id": row["id"]},
                row,
            )
            for offset, row in enumerate((first, second))
        ],
    ) == {"offset": 1, "commit_seq": 0}
    publication = dict(
        operation_id=opened["id"],
        authority=binding.authority,
        generation_id=generation_id,
        certificate=certificate,
    )
    with psycopg.connect(native_target) as connection:
        persist_verified_certificate(
            connection,
            **publication,
            verifier=FixtureCertificateVerifier(
                binding.authority, expected.certificate_ref
            ),
        )

    target_publication = Publication(restricted_target, timeout_ms=3000)
    before_observation = mirrors.get_mirror(mirror_id)
    with closing(CommandJournal(tmp_path)) as journal:
        runtime = CaptureRuntime(
            journal=journal,
            connect=None,
            signals=None,
            observe_committed_publication=target_publication.observe_committed,
        )
        reconcile = dict(
            mirror_id=mirror_id, operation_id=opened["id"], expected=expected
        )
        with pytest.raises(RuntimeBlocked, match="publication_observation_rejected"):
            runtime.reconcile_open_publication(**reconcile)
        assert target_publication.publish_generation(**publication) == generation_id
        for wrong in (
            replace(expected, completion_offset=13),
            replace(expected, certificate_ref="wrong-certificate"),
        ):
            with pytest.raises(
                RuntimeBlocked, match="publication_observation_rejected"
            ):
                runtime.reconcile_open_publication(**(reconcile | {"expected": wrong}))
        assert mirrors.get_mirror(mirror_id) == before_observation
        assert runtime.reconcile_open_publication(**reconcile) == "applied"
        assert runtime.reconcile_open_publication(**reconcile) == "already_applied"
    observed = mirrors.get_mirror(mirror_id)
    assert observed["published_generation_id"] == generation_id
    assert observed["history_epoch"] == expected.history_epoch
    assert [(op["id"], op["state"]) for op in observed["operations"]] == [
        (opened["id"], "applied")
    ]
    initial_position = dict(
        mirror_id=mirror_id,
        history_epoch=expected.history_epoch,
        commit_seq=0,
        entry_seq=0,
    )
    assert (
        observed["retained_lower_bound"]
        == observed["committed_upper_bound"]
        == initial_position
    )

    start = dict(
        channel_id=channel.id,
        channel_name=channel.name,
        target="published",
        ignore_checkpoints=False,
        actor_id=READER,
        trigger_node_id="nd_trigger",
        version=version.number,
        draft_revision=None,
        graph=version.graph,
        stop_at_node_id=None,
    )
    job, _ = mint_on_demand_run(**start)
    runs = get_run_store()
    worker_job, _ = mint_on_demand_run(**start)
    assert runs.get_run(worker_job.id).graph is None
    assert run_channel_job(worker_job.id) == {"status": "succeeded"}
    completed = get_job_store().get(worker_job.id)
    assert completed.status == "succeeded"
    assert completed.result == {
        "schema": "channel_run.v1",
        "channel_id": channel.id,
        "version": version.number,
        "outcome": "completed",
    }
    worker_run = runs.get_run(worker_job.id)
    assert worker_run.mirror_execution_user_id == READER
    assert worker_run.graph == version.graph
    trigger_execution, execution = runs.list_executions(worker_job.id)
    assert (trigger_execution.node_id, trigger_execution.status) == (
        start["trigger_node_id"],
        "succeeded",
    )
    assert (execution.node_id, execution.status) == (read_node["id"], "succeeded")
    assert execution.output == {
        "rows": [first, second],
        "generation_id": generation_id,
        "source_ids": [SOURCE],
        "freshness": "unknown",
    }
    assert worker_run.mirror_state["source_ids"] == [SOURCE]
    assert worker_run.mirror_state["pins"] == {
        mirror_id: {"generation_id": generation_id, "source_id": SOURCE}
    }

    run = runs.get_run(job.id)
    assert run.mirror_execution_user_id == READER
    page = mirror_reads.read_run_page(run, mirror_id=mirror_id, after_key=None, limit=1)
    assert page["rows"] == [first]
    assert page["generation_id"] == generation_id
    assert page["source_ids"] == [SOURCE]
    assert page["next_key"] == {"id": 1}
    next_page = dict(mirror_id=mirror_id, after_key=page["next_key"], limit=2)
    run = runs.get_run(job.id)
    assert run.mirror_state["pins"] == {
        mirror_id: {"generation_id": generation_id, "source_id": SOURCE}
    }
    assert mirror_reads.read_run_page(run, **next_page)["rows"] == [second]

    updated = {"id": 1, "value": "updated"}
    assert target.apply_batch(
        **delivery,
        records=[
            Record(
                2,
                binding.table_identity,
                binding.authority.capture_generation,
                "upsert",
                "live",
                {"id": 1},
                updated,
            ),
        ],
    ) == {"offset": 2, "commit_seq": 1}
    bound = mirror_reads.capture_run_history(run, mirror_id=mirror_id)
    assert bound["lower_bound"] == initial_position
    assert bound["upper_bound"] == dict(initial_position, commit_seq=1, entry_seq=1)
    history_page = dict(
        mirror_id=mirror_id,
        after=initial_position,
        through=bound["upper_bound"],
        limit=10,
    )
    run = runs.get_run(job.id)
    assert run.mirror_state["history_bounds"][mirror_id] == bound
    (entry,) = mirror_reads.read_run_history(run, **history_page)["entries"]
    assert (entry["generation_id"], entry["before"], entry["after"]) == (
        generation_id,
        first,
        updated,
    )

    revoked_job, _ = mint_on_demand_run(**start)
    assert get_job_store().get(revoked_job.id).status == "queued"
    assert runs.get_run(revoked_job.id).mirror_execution_user_id == READER
    assert delete_membership(READER)
    assert run_channel_job(revoked_job.id) == {"status": "failed"}
    denied = get_job_store().get(revoked_job.id)
    assert (denied.status, denied.error_code, denied.result) == (
        "failed",
        "AUTH_FORBIDDEN",
        None,
    )
    assert runs.list_executions(revoked_job.id) == []
    assert runs.get_run(revoked_job.id).mirror_state is None

    run = runs.get_run(job.id)
    with pytest.raises(mirror_reads.MirrorDataForbidden):
        mirror_reads.read_run_page(run, **next_page)
    with pytest.raises(mirror_reads.MirrorDataForbidden):
        mirror_reads.read_run_history(run, **history_page)
    with pytest.raises(AuthForbidden):
        mint_on_demand_run(**start)
    authorize_source_data(execution_user_id=PUBLISHER, source_id=SOURCE)

    create_membership(
        subject_type="user", subject_id=READER, target=SOURCE, level="viewer"
    )
    replacement_id = uuid4().hex
    replacement_operation = "fixture-replacement"
    replacement_partition = replace(
        binding.partition_identity, topic_incarnation_id="fixture-replacement-topic"
    )
    replacement_certificate = dict(
        certificate,
        operation_id=replacement_operation,
        generation_id=replacement_id,
        partition_identity=asdict(replacement_partition),
        end_offset=0,
        source_completion="fixture-replacement-snapshot-completed",
        durable_source_checkpoint="fixture-replacement-checkpoint",
        ordered_delivery_proof="fixture-replacement-seal-[0,1)",
    )
    replacement_publication = dict(
        operation_id=replacement_operation,
        authority=binding.authority,
        generation_id=replacement_id,
        certificate=replacement_certificate,
    )
    with psycopg.connect(native_target) as connection:
        bootstrap.create_generation(
            connection,
            mirror_id=mirror_id,
            generation_id=replacement_id,
            authority=binding.authority,
            operation_id=replacement_operation,
            table_identity=binding.table_identity,
            history_epoch=binding.history_epoch,
            schema_fingerprint=binding.schema_fingerprint,
            columns=binding.columns,
            key_columns=binding.key_columns,
            partition_identity=replacement_partition,
            start_offset=-1,
            require_prepared_fence=True,
        )
    replacement_row = {"id": 3, "value": "replacement"}
    replacement_progress = target.apply_batch(
        authority=binding.authority,
        generation_id=replacement_id,
        partition_identity=replacement_partition,
        records=[
            Record(
                0,
                binding.table_identity,
                binding.authority.capture_generation,
                "upsert",
                "baseline",
                {"id": 3},
                replacement_row,
            ),
        ],
    )
    assert replacement_progress["offset"] == 0
    with psycopg.connect(native_target) as connection:
        persist_verified_certificate(
            connection,
            **replacement_publication,
            verifier=FixtureCertificateVerifier(
                binding.authority,
                mirrors.publication_certificate_ref(replacement_certificate),
            ),
        )
    assert (
        target_publication.publish_generation(**replacement_publication)
        == replacement_id
    )

    resumed_page = mirror_reads.read_run_page(runs.get_run(job.id), **next_page)
    assert resumed_page["generation_id"] == generation_id
    assert resumed_page["rows"] == [second]
    assert resumed_page["next_key"] is None
    assert resumed_page["freshness"] == "stale"

    fresh_job, _ = mint_on_demand_run(**start)
    assert fresh_job.id != job.id
    fresh_page = mirror_reads.read_run_page(
        runs.get_run(fresh_job.id), mirror_id=mirror_id, after_key=None, limit=2
    )
    assert fresh_page["generation_id"] == replacement_id
    assert fresh_page["rows"] == [replacement_row]
