"""Exercise guarded target publication in the disposable PostgreSQL EOS rig."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from backend.core.errors import AppError
from backend.metadata.mirrors.authorization import authorize_source_data
from backend.metadata.mirrors.publication import Publication, persist_verified_certificate
from backend.metadata.mirrors.reads import Reads
from backend.metadata.mirrors.types import PartitionIdentity, ReadCommittedBounds
from backend.tests.cdc.signal import EMPTY_TABLE, POPULATED_TABLE, SnapshotSignalProbe
from backend.tests.test_capture_anchored_native import disposable_target
from backend.tests.test_capture_seal_native import (
    OFFSET_TOPIC,
    WAL_BUDGET,
    SealTarget,
    SealTrial,
    await_evidence,
    committed,
    connect_checkpoint,
    snapshot_terminals,
    source_position,
    transport_state,
    write_wal_witness,
)

pytestmark = pytest.mark.skipif(
    os.getenv('REFRAQ_CDC_PUBLISH_TRIAL') != '1', reason='disposable Docker publication trial only',
)


def snapshot(probe, operation, table, start, status, count, *, windows):
    end = snapshot_terminals(probe, operation, table, start, status, count, closed_windows=windows)
    records, observed_end = committed(probe, probe.notifications, start=start)
    assert observed_end == end
    terminals = snapshot_terminal_records(records, operation)
    return dict(operation=operation, table=table, signal_generation=probe.receipt(operation, table),
                notification_start=start, notification_end=end, terminals=terminals)


def snapshot_terminal_records(records, operation):
    terminals = [dict(offset=offset, key=key, event=event) for offset, key, event in records
                 if event['aggregate_type'] == 'Incremental Snapshot' and event['id'] == operation
                 and event['type'] in {'TABLE_SCAN_COMPLETED', 'COMPLETED'}]
    scan, complete = terminals
    assert [terminal['event']['type'] for terminal in terminals] == ['TABLE_SCAN_COMPLETED', 'COMPLETED']
    assert scan['offset'] < complete['offset']
    return terminals


@dataclass(frozen=True)
class WalWitness:
    xid: int
    wal_start: int
    wal_end: int
    commit_lsn: int
    data_topic: str
    data_record: tuple
    transaction_topic: str
    markers: tuple
    previous_checkpoint_offset: int

    def evidence(self, rig):
        data_offset, _, event = self.data_record
        begin, end = self.markers
        return dict(xid=self.xid, wal_start=self.wal_start, wal_end=self.wal_end, commit_lsn=self.commit_lsn,
                    table=POPULATED_TABLE, data_topic=self.data_topic, data_offset=data_offset,
                    data_lsn=event['source']['lsn'], data_partition=asdict(rig.partition(self.data_topic)),
                    transaction_topic=self.transaction_topic,
                    transaction_partition=asdict(rig.partition(self.transaction_topic)),
                    transaction_begin_offset=begin[0], transaction_begin_id=begin[2]['id'],
                    transaction_end_offset=end[0], transaction_end_id=end[2]['id'],
                    previous_checkpoint_offset=self.previous_checkpoint_offset)

    def observe(self, rig):
        probe = rig.probe
        wal = probe.profile.sql(f"""
            SELECT xid, start_lsn - '0/0'::pg_lsn, end_lsn - '0/0'::pg_lsn, resource_manager, record_type
            FROM pg_get_wal_record_info('0/0'::pg_lsn + {self.wal_start}::numeric);
        """)
        assert wal == f'{self.xid}|{self.wal_start}|{self.wal_end}|Transaction|COMMIT'
        records, eof = committed(probe, self.data_topic, start=self.data_record[0])
        assert records == [self.data_record], 'Retained witness data differs from the observed transaction'
        assert eof == rig.transport[self.data_topic][1].positions[1]
        records, eof = committed(probe, self.transaction_topic, start=self.markers[0][0])
        markers = tuple(record for record in records if record[2]['id'].startswith(f'{self.xid}:'))
        assert markers == self.markers and eof == rig.transport[self.transaction_topic][1].positions[1]


def checkpoint_after_snapshot(probe, transaction_topic, *, live, baseline):
    previous = connect_checkpoint(probe)
    assert previous is not None
    xid, first, end = write_wal_witness(probe)
    assert previous[1]['lsn'] < first < end
    data_topic = probe.topic(POPULATED_TABLE)
    data, _ = await_evidence(
        data_topic, lambda: committed(probe, data_topic, start=baseline[-1][0] + 1),
        lambda batch: bool(batch[0]),
    )
    assert probe.changes(POPULATED_TABLE, data) == [(5, 'c', 'false', None, 'seal-witness')]
    data_record, = data
    _, _, event = data_record
    assert event['source']['txId'] == xid and event['source']['lsn'] <= first
    assert all(prior['source']['lsn'] < first for _, _, prior in live)
    prefix = f'{xid}:'

    def transaction():
        records, _ = committed(probe, transaction_topic)
        return [(offset, key, value) for offset, key, value in records if value['id'].startswith(prefix)]

    markers = await_evidence(transaction_topic, transaction, lambda batch: bool(batch) and batch[-1][2]['status'] == 'END')
    assert [value['status'] for _, _, value in markers] == ['BEGIN', 'END']
    assert all(key == {'id': value['id']} for _, key, value in markers)
    begin, terminal_record = markers
    assert begin[0] < terminal_record[0]
    assert event['transaction']['id'] == begin[2]['id']
    _, _, terminal = terminal_record
    assert terminal['event_count'] == 1
    assert terminal['data_collections'] == [{'data_collection': POPULATED_TABLE, 'event_count': 1}]
    commit_lsn = int(terminal['id'].removeprefix(prefix))
    assert first <= commit_lsn <= end
    checkpoint = await_evidence(
        OFFSET_TOPIC, lambda: connect_checkpoint(probe),
        lambda observed: observed is not None and observed[1].get('lsn_commit', 0) >= first,
    )
    position, value, _ = checkpoint
    assert position > previous[0] and value['messageType'] == 'COMMIT' and value['txId'] == xid
    assert value['lsn'] == value['lsn_proc'] == value['lsn_commit'] == commit_lsn
    return checkpoint, WalWitness(xid, first, end, commit_lsn, data_topic, data_record, transaction_topic,
                                  tuple(markers), previous[0])


@dataclass
class QuiescedRig:
    probe: SnapshotSignalProbe
    lineage: tuple
    initial_restart: int
    acknowledged_wal: int
    started: float
    transport: dict
    checkpoint: tuple

    def partition(self, topic):
        identity, _ = self.transport[topic]
        return PartitionIdentity(*identity, 0)

    def observe(self):
        profile = self.probe.profile
        peers = json.loads(profile.docker('network', 'inspect', '-f', '{{json .Containers}}', profile.prefix))
        assert sorted(peer['Name'] for peer in peers.values()) == sorted([profile.prefix + 'pg', profile.prefix + 'broker'])
        lineage, wal = source_position(self.probe, active=False)
        assert lineage == self.lineage and wal[1] == self.acknowledged_wal
        assert wal[2] - self.initial_restart <= WAL_BUDGET
        assert connect_checkpoint(self.probe) == self.checkpoint
        assert transport_state(self.probe, self.transport, quiesced=True) == self.transport
        assert time.monotonic() - self.started <= 35
        return dict(network=profile.prefix, peers=sorted(peer['Name'] for peer in peers.values()),
                    slot=self.probe.slot, publication=self.probe.publication,
                    source_lineage=list(lineage), confirmed_flush_lsn=wal[1])


class DisposablePublicationVerifier:
    def __init__(self, rig, target, completion, witness, producer_exclusion, *, start, records):
        self.rig = rig
        self.target = target
        self.witness = witness
        notifications = rig.probe.notifications
        self.completion = dict(completion, notification_topic=notifications,
                               notification_partition=asdict(rig.partition(notifications)))
        _, bounds = rig.transport[target.binding.topic]
        assert target.partition == rig.partition(target.binding.topic)
        self.bounds = ReadCommittedBounds(*bounds.positions, bounds.epoch)
        expected_coverage = dict(start=start, end=self.bounds.stable, eof=self.bounds.stable,
                                 offsets=[offset for offset, _, _ in records],
                                 before=asdict(self.bounds), after=asdict(self.bounds), authority=asdict(target.authority))
        position, value, eof = rig.checkpoint
        empty_proof = None
        if completion['table'] == EMPTY_TABLE:
            scan = completion['terminals'][0]['event']['additional_data']
            assert (start, self.bounds.stable, records) == (0, 0, [])
            empty_proof = dict(source_rows=int(scan['total_rows_scanned']), exclusive_eof=self.bounds.stable)
        self.expected = dict(
            operation_id=completion['operation'], generation_id=target.generation, table_identity=completion['table'],
            capture_generation=target.authority.capture_generation, schema_fingerprint='signal-fixture',
            partition_identity=asdict(target.partition), end_offset=self.bounds.stable - 1,
            source_completion=self.completion,
            producer_exclusion=producer_exclusion, key_fingerprint=sha256(b'id').hexdigest(),
            durable_source_checkpoint=dict(topic=OFFSET_TOPIC, key=[rig.probe.connector_path.split('/')[1],
                                                                   {'server': rig.probe.source}],
                                           partition=asdict(rig.partition(OFFSET_TOPIC)), offset=position, eof=eof,
                                           value=value, wal_witness=witness.evidence(rig)),
            ordered_delivery_proof=expected_coverage,
            empty_table_proof=empty_proof if empty_proof is not None else False,
        )

    def verify(self, *, authority, certificate):
        target = self.target
        expected = self.expected
        if authority != target.authority or certificate != expected:
            raise ValueError('Disposable publication evidence does not match the operation')
        metadata, offset, proof = target.admin.execute(
            'SELECT source_mirror_state.delivery_metadata(id), applied_offset, anchored_coverage '
            'FROM source_mirror_state.generations WHERE id = %s', (target.generation,),
        ).fetchone()
        assert metadata['authority'] == asdict(authority) and metadata['mirror_id'] == target.mirror
        for field in ('operation_id', 'generation_id', 'table_identity', 'capture_generation',
                      'schema_fingerprint', 'partition_identity'):
            assert metadata[field] == expected[field]
        assert metadata['key_columns'] == ['id'] and not metadata['cleanup_pending']
        assert metadata['native_types'] == ({'id': 'integer'} if self.completion['table'] == EMPTY_TABLE
                                            else {'id': 'integer', 'value': 'text'})
        if offset != expected['end_offset'] or proof != expected['ordered_delivery_proof']:
            raise ValueError('Target coverage has not reached the sealed partition')
        assert self.rig.observe() == expected['producer_exclusion']
        probe = self.rig.probe
        completion = self.completion
        assert probe.receipt(completion['operation'], completion['table']) == completion['signal_generation']
        notifications = completion['notification_topic']
        records, eof = committed(probe, notifications, start=completion['notification_start'])
        assert completion['notification_end'] <= eof == self.rig.transport[notifications][1].positions[1]
        assert snapshot_terminal_records(records, completion['operation']) == completion['terminals']
        self.witness.observe(self.rig)
        assert time.monotonic() - self.rig.started <= 35
        return 'disposable-postgresql-eos-verifier'


@contextmanager
def gateway_engine(profile, admin, parameters):
    role = 'refraq_mirror_gateway'
    hba = profile.root / 'pg/hba'
    hba.chmod(0o644)
    with hba.open('a') as handle:
        handle.write(f'hostssl {admin.info.dbname} {role} all scram-sha-256\n')
    hba.chmod(0o444)
    password = token_hex(32)
    admin.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(role), sql.Literal(password)))
    assert admin.execute('SELECT pg_reload_conf()').fetchone() == (True,)
    engine = create_engine('postgresql+psycopg://', creator=lambda: psycopg.connect(
        **{**parameters, 'user': role, 'password': password},
    ))
    try:
        yield engine
    finally:
        engine.dispose()


def source_grants(admin):
    admin.execute('CREATE SCHEMA fixture_access')
    with admin.transaction():
        admin.execute('SET LOCAL search_path = fixture_access')
        admin.execute('CREATE TABLE roles (id text, key text, permissions jsonb)')
        admin.execute('CREATE TABLE users (id text, status text, identity_source text, role_id text)')
        admin.execute('CREATE TABLE source_memberships (target text, level text, subject_type text, subject_id text)')
        admin.execute('CREATE TABLE user_group_members (user_id text, group_id text)')
        admin.execute('CREATE TABLE user_groups (id text)')
        admin.execute("INSERT INTO roles VALUES ('role', 'test_reader', '[\"sources:data_read\"]')")
        admin.execute("INSERT INTO users VALUES ('reader', 'active', 'local', 'role')")
        admin.execute("INSERT INTO source_memberships VALUES ('source-a', 'viewer', 'user', 'reader'), "
                      "('source-b', 'viewer', 'user', 'reader')")
        admin.execute('GRANT USAGE ON SCHEMA fixture_access TO refraq_mirror_gateway')
        admin.execute('GRANT SELECT ON ALL TABLES IN SCHEMA fixture_access TO refraq_mirror_gateway')


def rig_publications(profile, admin, owner):
    probe = SnapshotSignalProbe(profile)
    probe.configure()
    profile.sql('CREATE EXTENSION pg_walinspect;')
    data_topic, empty_topic = map(probe.topic, (POPULATED_TABLE, EMPTY_TABLE))
    transaction_topic = f'{probe.source}.transaction'
    profile.kafka.create_topic(transaction_topic)
    topics = (data_topic, empty_topic, probe.notifications, OFFSET_TOPIC, transaction_topic)
    lineage, initial_wal = source_position(probe, active=True)
    initial = transport_state(probe, topics)
    profile.sql(f"INSERT INTO {POPULATED_TABLE} VALUES (4, 'live');")
    live, _ = await_evidence(data_topic, lambda: committed(probe, data_topic), lambda batch: bool(batch[0]))
    assert probe.changes(POPULATED_TABLE, live) == [(4, 'c', 'false', None, 'live')]

    empty = probe.submit(EMPTY_TABLE)
    empty_snapshot = snapshot(probe, empty, EMPTY_TABLE, 0, 'EMPTY', 0, windows=1)
    empty_target = SealTarget(probe, admin, owner, EMPTY_TABLE, empty, initial, 'a')
    operation, signal_generation = str(uuid4()), str(uuid4())
    profile.sql(f"INSERT INTO snapshot_binding VALUES ('{operation}', '{signal_generation}', '{POPULATED_TABLE}');")
    target = SealTarget(probe, admin, owner, POPULATED_TABLE, operation, initial, 'b')
    target.apply_visible_prefix(live[0][0])
    delayed_cursor = target.state()[0] + 1
    assert profile.sql(probe.signal_insert(operation, POPULATED_TABLE)) == operation
    completed = snapshot(probe, operation, POPULATED_TABLE, empty_snapshot['notification_end'],
                         'SUCCEEDED', 3, windows=2)
    baseline, _ = await_evidence(data_topic, lambda: committed(probe, data_topic, start=delayed_cursor),
                                 lambda batch: len(batch[0]) >= 3)
    assert sorted(probe.changes(POPULATED_TABLE, baseline)) == [
        (1, 'r', 'incremental', None, 'before-delete'), (2, 'r', 'incremental', None, 'before-update'),
        (4, 'r', 'incremental', None, 'live'),
    ]
    checkpoint, witness = checkpoint_after_snapshot(probe, transaction_topic, live=live, baseline=baseline)
    active_lineage, active_wal = await_evidence(
        probe.slot, lambda: source_position(probe, active=True), lambda observed: observed[1][1] >= witness.wal_end,
    )
    assert active_lineage == lineage
    started = time.monotonic()
    worker = profile.prefix + 'worker'
    profile.docker('stop', '--timeout', '15', worker)
    profile.docker('rm', worker)
    quiesced_lineage, quiesced_wal = source_position(probe, active=False)
    assert quiesced_lineage == lineage and quiesced_wal[1] >= active_wal[1]
    sealed = transport_state(probe, topics, quiesced=True)
    for topic in topics:
        assert (sealed[topic][0], sealed[topic][1].epoch) == (initial[topic][0], initial[topic][1].epoch)
    assert checkpoint[0] < checkpoint[2] == sealed[OFFSET_TOPIC][1].positions[1]
    assert witness.markers[-1][0] < sealed[transaction_topic][1].positions[1]
    assert completed['notification_end'] == sealed[probe.notifications][1].positions[1]
    assert committed(probe, empty_topic) == ([], 0)
    data, data_end = committed(probe, data_topic)
    witness_offset = witness.data_record[0]
    assert data_end == sealed[data_topic][1].positions[1] > witness_offset + 1
    assert data == live + baseline + [witness.data_record]
    assert profile.kafka.scan(data_topic, start=witness_offset + 1, committed=False) == ([], data_end)
    assert target.state()[0] + 1 == delayed_cursor <= baseline[0][0] < witness_offset
    assert empty_target.state()[:2] == (-1, None)
    delayed = baseline + [witness.data_record]
    rig = QuiescedRig(probe, lineage, initial_wal[0], quiesced_wal[1], started, sealed, checkpoint)
    exclusion = rig.observe()
    print(f'publish delay target_cursor={delayed_cursor} notification_eof={completed["notification_end"]} '
          f'wal_witness={witness.evidence(rig)} checkpoint_offset={checkpoint[0]} sealed_eof={data_end}')
    return (
        DisposablePublicationVerifier(rig, empty_target, empty_snapshot, witness, exclusion, start=0, records=[]),
        DisposablePublicationVerifier(rig, target, completed, witness, exclusion, start=delayed_cursor, records=delayed),
    )


def lose_reply_after_commit(call):
    call()
    raise ConnectionError('fixture lost reply after commit')


@contextmanager
def target_rejects(code):
    with pytest.raises(DBAPIError) as rejected:
        yield
    assert (rejected.value.orig.sqlstate, rejected.value.orig.diag.message_primary) == ('P0001', code)


def guarded_publication(verifier, applier, reads, parameters, expected_rows):
    target = verifier.target
    certificate = deepcopy(verifier.expected)
    operation = certificate['operation_id']
    request = dict(operation_id=operation, authority=target.authority, generation_id=target.generation,
                   certificate=certificate)
    read_request = dict(run_id=f'run-{target.generation}', mirror_id=target.mirror, execution_user_id='reader')
    publication = Publication(applier)

    def persist(evidence):
        with psycopg.connect(**parameters, autocommit=True) as connection:
            persist_verified_certificate(connection, **{**request, 'certificate': evidence}, verifier=verifier)

    def observe():
        with psycopg.connect(**parameters, autocommit=True) as connection:
            return connection.execute(
                'SELECT m.published_generation_id, m.history_epoch, g.status, to_jsonb(c), '
                '(SELECT generation_id FROM source_mirror_state.reader_pins WHERE run_id = %s AND mirror_id = m.id) '
                'FROM source_mirror_state.mirrors m JOIN source_mirror_state.generations g ON g.mirror_id = m.id '
                'LEFT JOIN source_mirror_state.certificates c ON c.operation_id = g.operation_id '
                'WHERE m.id = %s AND g.id = %s', (read_request['run_id'], target.mirror, target.generation),
            ).fetchone()

    unverified = (None, 'history-epoch', 'building', None, None)
    with pytest.raises(ValueError, match='Target coverage has not reached'):
        persist(certificate)
    assert observe() == unverified
    assert target.seal(verifier.bounds) == certificate['end_offset'] + 1
    forged = deepcopy(certificate)
    forged['durable_source_checkpoint']['wal_witness']['xid'] += 1
    with pytest.raises(ValueError, match='evidence does not match'):
        persist(forged)
    with target_rejects('MIRROR_PUBLICATION_BLOCKED'):
        publication.publish_generation(**request)
    with target_rejects('MIRROR_READ_UNAVAILABLE'):
        reads.acquire_pin(**read_request)
    assert observe() == unverified

    with pytest.raises(ConnectionError, match='fixture lost reply after commit'):
        lose_reply_after_commit(lambda: persist(certificate))
    verified = dict(operation_id=operation, generation_id=target.generation, authority=asdict(target.authority),
                    evidence=certificate, verified_by='disposable-postgresql-eos-verifier', published=False)
    pending = (None, 'history-epoch', 'building', verified, None)
    assert observe() == pending
    persist(certificate)
    changed = {**certificate, 'key_fingerprint': '0' * 64}
    with target_rejects('MIRROR_PUBLICATION_BLOCKED'):
        publication.publish_generation(**{**request, 'certificate': changed})
    assert observe() == pending

    with applier.connect() as connection:
        original_pid = connection.exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
    with pytest.raises(ConnectionError, match='fixture lost reply after commit'):
        lose_reply_after_commit(lambda: publication.publish_generation(**request))
    applier.dispose()
    published = (target.generation, 'history-epoch', 'published', {**verified, 'published': True})
    assert observe() == (*published, None)
    pin = reads.acquire_pin(**read_request)
    page_request = dict(pin=pin, execution_user_id='reader', after_key=None, limit=20)
    page = reads.read_page(**page_request)
    pinned = (*published, target.generation)
    assert observe() == pinned
    with applier.connect() as connection:
        assert connection.exec_driver_sql('SELECT pg_backend_pid()').scalar_one() != original_pid
    assert publication.publish_generation(**request) == target.generation
    assert observe() == pinned
    assert reads.acquire_pin(**read_request) == pin
    assert reads.read_page(**page_request) == page
    assert (page['generation_id'], page['source_ids'], page['rows'], page['next_key']) == (
        target.generation, [target.authority.source_id], expected_rows, None,
    )
    print(f'published operation={operation} generation={target.generation} end_offset={certificate["end_offset"]} '
          f'history_epoch={published[1]} authorized_rows={len(expected_rows)}')
    return pin


def test_quiesced_native_seal_publishes_once_and_recovers_authorized_rows():
    with TemporaryDirectory(prefix='refraq-cdc-publish-') as directory:
        profile = SealTrial(Path(directory))
        try:
            profile.setup()
            with disposable_target(profile) as (admin, applier):
                parameters = dict(admin.info.get_parameters(), password=admin.info.password)
                owner = create_engine('postgresql+psycopg://', creator=lambda: psycopg.connect(**{
                    **parameters, 'options': '-c role=refraq_mirror_owner -c statement_timeout=4000',
                }))
                try:
                    with gateway_engine(profile, admin, parameters) as gateway:
                        for engine, role in ((owner, 'refraq_mirror_owner'), (applier, 'refraq_mirror_applier'),
                                             (gateway, 'refraq_mirror_gateway')):
                            with engine.connect() as connection:
                                assert connection.exec_driver_sql('SELECT current_user').scalar_one() == role
                        source_grants(admin)

                        def authorize(**request):
                            with gateway.begin() as session:
                                session.execute(text('SET LOCAL search_path = fixture_access'))
                                authorize_source_data(session=session, **request)

                        reads = Reads(gateway, authorize_source_read=authorize, verify_terminal_proof=pytest.fail)
                        empty, populated = rig_publications(profile, admin, owner)
                        empty_pin = guarded_publication(empty, applier, reads, parameters, [])
                        pin = guarded_publication(populated, applier, reads, parameters, [
                            {'id': 1, 'value': 'before-delete'}, {'id': 2, 'value': 'before-update'},
                            {'id': 4, 'value': 'live'}, {'id': 5, 'value': 'seal-witness'},
                        ])
                        page_request = dict(pin=pin, execution_user_id='reader', after_key=None, limit=20)
                        role_permissions = 'UPDATE fixture_access.roles SET permissions = %s::jsonb WHERE id = \'role\''
                        assert admin.execute(role_permissions, ('[]',)).rowcount == 1
                        with pytest.raises(AppError) as role_denied:
                            reads.read_page(**page_request)
                        assert (role_denied.value.code, role_denied.value.http_status) == ('AUTH_FORBIDDEN', 403)
                        assert admin.execute(role_permissions, ('["sources:data_read"]',)).rowcount == 1
                        assert admin.execute('DELETE FROM fixture_access.source_memberships WHERE target = %s',
                                             (pin.source_id,)).rowcount == 1
                        with pytest.raises(AppError) as source_denied:
                            reads.read_page(**page_request)
                        assert (source_denied.value.code, source_denied.value.http_status) == ('AUTH_FORBIDDEN', 403)
                        assert reads.read_page(**{**page_request, 'pin': empty_pin})['source_ids'] == [empty_pin.source_id]
                        populated.rig.observe()
                finally:
                    owner.dispose()
        finally:
            profile.clean()
