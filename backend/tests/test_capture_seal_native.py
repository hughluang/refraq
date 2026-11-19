"""Measure a same-primary snapshot checkpoint and seal in the disposable EOS rig."""

from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from confluent_kafka import Consumer
import psycopg
from psycopg import sql
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import DBAPIError

from backend.metadata.capture.delivery import DeliveryBinding, DeliveryLimits, KafkaDelivery, KafkaIdentity
from backend.metadata.capture.runtime_store import RuntimeBlocked
from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.bootstrap import create_generation
from backend.metadata.mirrors.types import (
    AnchoredProfile, AnchoredScan, Authority, PartitionIdentity, ReadCommittedBounds, Record, SealedScan,
)
from backend.tests.cdc.eos import CONNECTOR, EosTrial
from backend.tests.cdc.signal import EMPTY_TABLE, POPULATED_TABLE, SnapshotSignalProbe
from backend.tests.test_capture_anchored_native import disposable_target

pytestmark = pytest.mark.skipif(os.getenv('REFRAQ_CDC_SEAL_TRIAL') != '1', reason='disposable Docker seal trial only')

OFFSET_TOPIC = 'offsets'
WAL_BUDGET = 64 * 1024 * 1024


class SealTrial(EosTrial):
    def rest(self, path, *opts, **kwargs):
        if path.startswith('connectors/snapshot-') and path.endswith('/config') and '-X' in opts:
            config = json.loads(kwargs['data'])
            assert all(config.get(key) == value for key, value in CONNECTOR.items())
            kwargs['data'] = json.dumps({**config, 'provide.transaction.metadata': 'true'})
        return super().rest(path, *opts, **kwargs)


class SignalFixtureDecoder:
    """Translate the signal fixture's schemaless wire format for the target test."""

    def __init__(self, probe, table, capture_generation):
        self.probe = probe
        self.table = table
        self.capture_generation = capture_generation

    def decode(self, *, offset, key, value):
        event = json.loads(value)
        ((key_id, operation, snapshot, _, _),) = self.probe.changes(
            self.table, [(offset, json.loads(key), event)],
        )
        assert (operation, snapshot) in {('c', 'false'), ('r', 'incremental')}
        assert event['after']['id'] == key_id
        return Record(offset, self.table, self.capture_generation, 'upsert',
                      'baseline' if operation == 'r' else 'live', {'id': key_id}, event['after'])


class SealTarget:
    def __init__(self, probe, admin, owner, table, operation, initial, suffix):
        self.probe = probe
        self.admin = admin
        topic = probe.topic(table)
        identity, bounds = initial[topic]
        self.anchored = AnchoredProfile(bounds.epoch)
        self.partition = PartitionIdentity(*identity, 0)
        self.authority = Authority(f'source-{suffix}', 'binding', 1, 'runtime', 1, 1, 'capture')
        self.generation = suffix * 32
        self.binding = DeliveryBinding(self.authority, self.generation, self.partition, topic)
        self.application = Application(owner)
        self.decoder = SignalFixtureDecoder(probe, table, self.authority.capture_generation)
        self.request = dict(authority=self.authority, generation_id=self.generation,
                            partition_identity=self.partition, anchored_profile=self.anchored)
        self.mirror = 'mir_' + suffix * 32
        columns = {'id': 'integer', 'value': 'text'} if table == POPULATED_TABLE else {'id': 'integer'}
        create_generation(admin, mirror_id=self.mirror, generation_id=self.generation, authority=self.authority,
                          table_identity=table, history_epoch='history-epoch', operation_id=operation,
                          schema_fingerprint='signal-fixture', columns=columns, key_columns=('id',),
                          partition_identity=self.partition, start_offset=-1)
        self.target_table, = admin.execute(
            'UPDATE source_mirror_state.generations SET anchored_profile = %s::jsonb WHERE id = %s RETURNING table_name',
            (json.dumps(asdict(self.anchored)), self.generation),
        ).fetchone()

    @contextmanager
    def reader(self, *, eof):
        kafka = self.probe.profile.kafka

        @contextmanager
        def admit(**request):
            assert request['binding'] == self.binding
            yield

        delivery = KafkaDelivery(
            consumer=Consumer({**kafka.config, 'group.id': f'seal-{self.generation}', 'isolation.level': 'read_committed',
                               'enable.auto.commit': False, 'enable.auto.offset.store': False,
                               'auto.offset.reset': 'error', 'allow.auto.create.topics': False,
                               'enable.partition.eof': eof, 'check.crcs': True,
                               'queued.max.messages.kbytes': 1024, 'fetch.max.bytes': 1024 * 1024}),
            identity=KafkaIdentity(kafka.admin), application=self.application, binding=self.binding,
            decoder=self.decoder, admission=admit, anchored_profile=self.anchored,
            limits=DeliveryLimits(poll_seconds=3),
        )
        try:
            yield delivery
        finally:
            delivery.close()

    def state(self):
        offset, proof, commit_seq = self.admin.execute(
            'SELECT g.applied_offset, g.anchored_coverage, m.commit_seq '
            'FROM source_mirror_state.generations g JOIN source_mirror_state.mirrors m ON m.id = g.mirror_id '
            'WHERE g.id = %s', (self.generation,),
        ).fetchone()
        rows = self.admin.execute(sql.SQL('SELECT * FROM source_mirror.{} ORDER BY id').format(
            sql.Identifier(self.target_table),
        )).fetchall()
        history = self.admin.execute("SELECT after_image->>'id', after_image->>'value' "
                                     'FROM source_mirror_state.live_log WHERE mirror_id = %s '
                                     'ORDER BY commit_seq, entry_seq', (self.mirror,)).fetchall()
        return offset, proof, rows, history, commit_seq

    def apply_visible_prefix(self, last_visible):
        deadline = time.monotonic() + 8
        with self.reader(eof=False) as delivery:
            while self.state()[0] < last_visible:
                assert time.monotonic() < deadline
                delivery.poll_once()
        assert self.state()[0] == last_visible

    def seal(self, bounds):
        with self.reader(eof=True) as delivery:
            return delivery.apply_sealed_range(partition_identity=self.partition, seal=bounds)


def committed(probe, topic, *, start=0):
    records, end = probe.profile.kafka.scan(topic, start=start, committed=True)
    return [(offset, json.loads(key), json.loads(value) if value is not None else None)
            for offset, key, value in records], end


def await_evidence(topic, observe, accept):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        evidence = observe()
        if accept(evidence):
            return evidence
        time.sleep(0.25)
    pytest.fail(f'No matching evidence on {topic}. Last observation: {evidence!r}')


def snapshot_terminals(probe, operation, table, start, status, count, *, closed_windows):
    records, end = await_evidence(
        probe.notifications, lambda: committed(probe, probe.notifications, start=start),
        lambda batch: any(event['type'] == 'COMPLETED' for _, _, event in batch[0]),
    )
    assert all(event['aggregate_type'] == 'Initial Snapshot' and event['type'] == 'SKIPPED'
               for _, _, event in records if event['aggregate_type'] != 'Incremental Snapshot')
    incremental = [(offset, key, event) for offset, key, event in records
                   if event['aggregate_type'] == 'Incremental Snapshot']
    for _, key, event in incremental:
        assert key == {'id': operation} and event['id'] == operation
        assert event['additional_data']['connector_name'] == probe.source
    assert [event['type'] for _, _, event in incremental if event['type'] != 'IN_PROGRESS'] == [
        'STARTED', 'DATA_COLLECTIONS_RESOLVED', 'TABLE_SCAN_COMPLETED', 'COMPLETED',
    ]
    for _, _, event in incremental[:2]:
        assert event['additional_data']['data_collections'] == table
    scan, complete = incremental[-2:]
    data = scan[2]['additional_data']
    assert (data['scanned_collection'], data['status'], int(data['total_rows_scanned'])) == (table, status, count)
    probe.verify_terminal_watermark(operation, table, {'COMPLETED': int(complete[2]['timestamp'])},
                                    closed_windows=closed_windows)
    print(f'terminals operation={operation} table={table} status={status} rows={count} '
          f'partition=0 scan={scan[0]} complete={complete[0]} committed_eof={end}')
    return end


def source_position(probe, *, active):
    result = probe.profile.sql(f"""
        SELECT (pg_control_system()).system_identifier, (pg_control_checkpoint()).timeline_id, publication.oid,
               slot.active, slot.restart_lsn - '0/0'::pg_lsn, slot.confirmed_flush_lsn - '0/0'::pg_lsn,
               pg_current_wal_flush_lsn() - '0/0'::pg_lsn
        FROM pg_replication_slots slot CROSS JOIN pg_publication publication
        WHERE slot.slot_name = '{probe.slot}' AND publication.pubname = '{probe.publication}'
          AND slot.plugin = 'pgoutput' AND slot.database = current_database() AND slot.wal_status = 'reserved'
          AND slot.invalidation_reason IS NULL AND NOT slot.failover AND NOT slot.synced
          AND NOT pg_is_in_recovery();
    """)
    system, timeline, publication, is_active, restart, confirmed, flush = result.split('|')
    assert (is_active == 't') == active
    restart, confirmed, flush = map(int, (restart, confirmed, flush))
    assert 0 < restart <= confirmed <= flush and flush - restart <= WAL_BUDGET
    slot = probe.profile.exe('pg', 'sh', '-ec', f'stat -c %d:%i "$PGDATA/pg_replslot/{probe.slot}"')
    return (system, timeline, publication, slot), (restart, confirmed, flush)


def write_wal_witness(probe):
    xid, commit_start, commit_end = probe.profile.sql(f"""
        SELECT pg_current_wal_insert_lsn() AS first_wal \\gset
        BEGIN;
        SET LOCAL synchronous_commit = on;
        INSERT INTO {POPULATED_TABLE} VALUES (5, 'seal-witness');
        SELECT pg_current_xact_id()::xid AS witness_xid \\gset
        COMMIT;
        SELECT xid, start_lsn - '0/0'::pg_lsn, end_lsn - '0/0'::pg_lsn
        FROM pg_get_wal_records_info(:'first_wal', pg_current_wal_flush_lsn())
        WHERE xid = :'witness_xid'::xid AND resource_manager = 'Transaction' AND record_type = 'COMMIT';
    """).split('|')
    return int(xid), int(commit_start), int(commit_end)


def connect_checkpoint(probe):
    records, end = committed(probe, OFFSET_TOPIC)
    expected_key = [probe.connector_path.split('/')[1], {'server': probe.source}]
    matching = [(offset, value) for offset, key, value in records if key == expected_key]
    if matching:
        offset, value = matching[-1]
        assert value is not None, 'Connect checkpoint was deleted'
        return offset, value, end
    return None


def transport_state(probe, topics, *, quiesced=False):
    result = {}
    for topic in topics:
        identity = probe.profile.kafka.identity(topic)
        bounds = probe.profile.kafka.bounds(topic)
        low, stable, high = bounds.positions
        assert low == 0
        if quiesced:
            assert stable == high, (topic, bounds)
        result[topic] = (identity, bounds)
    assert len({identity[0] for identity, _ in result.values()}) == 1
    return result


def test_snapshot_terminals_precede_quiesced_durable_seal():
    with TemporaryDirectory(prefix='refraq-cdc-seal-') as directory:
        profile = SealTrial(Path(directory))
        try:
            profile.setup()
            with disposable_target(profile) as (admin, applier):
                parameters = dict(admin.info.get_parameters(), password=admin.info.password,
                                  options='-c role=refraq_mirror_owner -c statement_timeout=4000')
                owner = create_engine('postgresql+psycopg://', creator=lambda: psycopg.connect(**parameters))
                try:
                    with owner.connect() as connection:
                        assert connection.exec_driver_sql('SELECT current_user').scalar_one() == 'refraq_mirror_owner'
                    measure_seal(profile, admin, owner, applier)
                finally:
                    owner.dispose()
        finally:
            profile.clean()


def measure_seal(profile, admin, owner, applier):
    probe = SnapshotSignalProbe(profile)
    probe.configure()
    profile.sql('CREATE EXTENSION pg_walinspect;')
    empty_topic, data_topic = map(probe.topic, (EMPTY_TABLE, POPULATED_TABLE))
    transaction_topic = f'{probe.source}.transaction'
    profile.kafka.create_topic(transaction_topic)
    topics = (empty_topic, data_topic, probe.notifications, OFFSET_TOPIC, transaction_topic)
    source_lineage, initial_wal = source_position(probe, active=True)
    initial = transport_state(probe, topics)
    profile.sql(f"INSERT INTO {POPULATED_TABLE} VALUES (4, 'live');")
    await_evidence(data_topic, lambda: committed(probe, data_topic), lambda batch: bool(batch[0]))

    empty = probe.submit(EMPTY_TABLE)
    empty_end = snapshot_terminals(probe, empty, EMPTY_TABLE, 0, 'EMPTY', 0, closed_windows=1)
    assert committed(probe, empty_topic) == ([], 0)
    populated = probe.submit(POPULATED_TABLE)
    populated_end = snapshot_terminals(probe, populated, POPULATED_TABLE, empty_end, 'SUCCEEDED', 3, closed_windows=2)
    before_witness, _ = await_evidence(
        data_topic, lambda: committed(probe, data_topic), lambda batch: len(batch[0]) >= 4,
    )
    assert probe.changes(POPULATED_TABLE, before_witness[:1]) == [(4, 'c', 'false', None, 'live')]
    assert sorted(probe.changes(POPULATED_TABLE, before_witness[1:])) == [
        (1, 'r', 'incremental', None, 'before-delete'),
        (2, 'r', 'incremental', None, 'before-update'),
        (4, 'r', 'incremental', None, 'live'),
    ]
    empty_target = SealTarget(probe, admin, owner, EMPTY_TABLE, empty, initial, 'a')
    final_target = SealTarget(probe, admin, owner, POPULATED_TABLE, populated, initial, 'b')
    tail_target = SealTarget(probe, admin, owner, POPULATED_TABLE, f'{populated}-tail-fixture', initial, 'c')
    final_target.apply_visible_prefix(before_witness[-1][0])
    with pytest.raises(DBAPIError, match='permission denied for function apply_batch'):
        Application(applier).apply_batch(**empty_target.request, records=[])
    with pytest.raises(DBAPIError, match='MIRROR_COVERAGE_PROFILE_MISMATCH'):
        Application(applier).apply_batch(**{key: value for key, value in empty_target.request.items()
                                           if key != 'anchored_profile'}, records=[])

    previous = connect_checkpoint(probe)
    assert previous is not None
    xid, commit_start, commit_end = write_wal_witness(probe)
    assert previous[1]['lsn'] < commit_start < commit_end
    witness, _ = await_evidence(
        data_topic, lambda: committed(probe, data_topic, start=before_witness[-1][0] + 1),
        lambda batch: bool(batch[0]),
    )
    assert probe.changes(POPULATED_TABLE, witness) == [(5, 'c', 'false', None, 'seal-witness')]
    witness_offset, _, witness_event = witness[0]
    assert witness_event['source']['txId'] == xid
    assert witness_event['source']['lsn'] < commit_end
    witness_prefix = f'{xid}:'
    assert witness_event['transaction']['id'].startswith(witness_prefix)
    transaction_records, _ = await_evidence(
        transaction_topic, lambda: committed(probe, transaction_topic),
        lambda batch: any(event['id'].startswith(witness_prefix) and event['status'] == 'END'
                          for _, _, event in batch[0]),
    )
    transaction = [(offset, key, event) for offset, key, event in transaction_records
                   if event['id'].startswith(witness_prefix)]
    assert [event['status'] for _, _, event in transaction] == ['BEGIN', 'END']
    assert all(key == {'id': event['id']} for _, key, event in transaction)
    transaction_end_offset, _, transaction_end = transaction[-1]
    assert transaction_end['event_count'] == 1
    assert transaction_end['data_collections'] == [{'data_collection': POPULATED_TABLE, 'event_count': 1}]
    end_lsn = int(transaction_end['id'].removeprefix(witness_prefix))
    assert commit_start <= end_lsn <= commit_end
    checkpoint = await_evidence(
        OFFSET_TOPIC, lambda: connect_checkpoint(probe),
        lambda observed: observed is not None and observed[1].get('lsn_commit', 0) >= commit_start,
    )
    checkpoint_offset, source_offset, checkpoint_end = checkpoint
    assert checkpoint_offset > previous[0]
    assert source_offset['messageType'] == 'COMMIT'
    assert source_offset['lsn_commit'] == end_lsn
    assert source_offset['lsn'] == source_offset['lsn_proc'] == source_offset['lsn_commit']
    assert source_offset['txId'] == xid
    active_lineage, before_stop_wal = await_evidence(
        probe.slot, lambda: source_position(probe, active=True), lambda observed: observed[1][1] >= commit_end,
    )
    assert active_lineage == source_lineage
    print(f'checkpoint topic={OFFSET_TOPIC} partition=0 previous={previous[0]} position={checkpoint_offset} '
          f'xid={xid} wal_commit=[{commit_start},{commit_end}] data_position={witness_offset} '
          f'transaction_end_position={transaction_end_offset} '
          f'source_offset={source_offset}')

    quiescence_started = time.monotonic()
    worker = profile.prefix + 'worker'
    profile.docker('stop', '--timeout', '15', worker)
    profile.docker('rm', worker)
    peers = json.loads(profile.docker('network', 'inspect', '-f', '{{json .Containers}}', profile.prefix))
    assert {peer['Name'] for peer in peers.values()} == {profile.prefix + 'pg', profile.prefix + 'broker'}
    quiesced_lineage, quiesced_wal = source_position(probe, active=False)
    assert quiesced_lineage == source_lineage and quiesced_wal[1] >= before_stop_wal[1]
    sealed = transport_state(probe, topics, quiesced=True)
    for topic in topics:
        initial_identity, initial_bounds = initial[topic]
        identity, bounds = sealed[topic]
        assert (identity, bounds.epoch) == (initial_identity, initial_bounds.epoch)
    assert connect_checkpoint(probe) == checkpoint
    assert checkpoint_offset < checkpoint_end == sealed[OFFSET_TOPIC][1].positions[1]
    assert transaction_end_offset < sealed[transaction_topic][1].positions[1]
    assert sealed[empty_topic][1].positions[1] == 0
    assert committed(probe, empty_topic) == ([], 0)
    data_end = sealed[data_topic][1].positions[1]
    assert committed(probe, data_topic) == (before_witness + witness, data_end)
    assert data_end > witness_offset + 1
    assert committed(probe, data_topic, start=witness_offset + 1) == ([], data_end)
    assert profile.kafka.scan(data_topic, start=witness_offset + 1, committed=False) == ([], data_end)
    assert populated_end == sealed[probe.notifications][1].positions[1]
    assert committed(probe, probe.notifications, start=populated_end) == ([], populated_end)
    empty_bounds = ReadCommittedBounds(*sealed[empty_topic][1].positions, sealed[empty_topic][1].epoch)
    data_bounds = ReadCommittedBounds(*sealed[data_topic][1].positions, sealed[data_topic][1].epoch)
    assert empty_target.state() == (-1, None, [], [], 0)
    with pytest.raises(DBAPIError, match='MIRROR_COVERAGE_INVALID'):
        empty_target.application.apply_batch(**empty_target.request, records=[],
                                             scan=AnchoredScan(0, 0, empty_bounds, empty_bounds, ()))
    assert empty_target.seal(empty_bounds) == 0
    tail_target.apply_visible_prefix(witness_offset)
    tail_commit_seq = tail_target.state()[4]
    before_failure = final_target.state()
    candidate = SealedScan(before_failure[0] + 1, data_end, data_bounds, data_bounds, (), data_end)
    for malformed in (replace(candidate, start=before_failure[0]), replace(candidate, eof=data_end - 1),
                      replace(candidate, after=replace(data_bounds, high=data_end + 1))):
        with pytest.raises(DBAPIError, match='MIRROR_COVERAGE_INVALID'):
            final_target.application.apply_batch(**final_target.request, records=[], scan=malformed)
    assert final_target.state() == before_failure
    admin.execute(sql.SQL("ALTER TABLE source_mirror_state.generations ADD CONSTRAINT deny_fixture_seal "
                          "CHECK (anchored_coverage->'eof' IS NULL OR id <> {}) NOT VALID").format(
        sql.Literal(final_target.generation),
    ))
    constraints = []

    def observe_constraint(context):
        if isinstance(context.original_exception, psycopg.errors.CheckViolation):
            constraints.append(context.original_exception.diag.constraint_name)

    event.listen(owner, 'handle_error', observe_constraint)
    try:
        with pytest.raises(RuntimeBlocked, match='capture_delivery_blocked'):
            final_target.seal(data_bounds)
        assert constraints == ['deny_fixture_seal']
        assert final_target.state() == before_failure
    finally:
        event.remove(owner, 'handle_error', observe_constraint)
        admin.execute('ALTER TABLE source_mirror_state.generations DROP CONSTRAINT deny_fixture_seal')
    assert final_target.seal(data_bounds) == data_end
    assert tail_target.seal(data_bounds) == data_end
    for target, start, end, offsets, expected_commit_seq in (
        (empty_target, 0, 0, [], 0),
        (final_target, before_failure[0] + 1, data_end, [witness_offset], before_failure[4] + 1),
        (tail_target, witness_offset + 1, data_end, [], tail_commit_seq),
    ):
        offset, proof, rows, history, commit_seq = target.state()
        assert offset == end - 1
        assert commit_seq == expected_commit_seq
        assert (proof['start'], proof['end'], proof['eof'], proof['offsets']) == (start, end, end, offsets)
        assert proof['authority'] == asdict(target.authority)
        bounds = empty_bounds if target is empty_target else data_bounds
        assert proof['before'] == proof['after'] == asdict(bounds)
        if target is empty_target:
            assert rows == history == []
        else:
            assert rows == [(1, 'before-delete'), (2, 'before-update'), (4, 'live'), (5, 'seal-witness')]
            assert history == [('4', 'live'), ('5', 'seal-witness')]
        assert target.seal(bounds) == end
        assert target.state() == (offset, proof, rows, history, commit_seq)
        print(f'target_seal table={target.decoder.table} range=[{start},{end}) eof={end} '
              f'offsets={offsets} applied={offset} rows={len(rows)} live_entries={len(history)}')
    sealed_target_state = final_target.state()
    advanced = replace(data_bounds, stable=data_end + 1, high=data_end + 1)
    later_record = Record(data_end, POPULATED_TABLE, final_target.authority.capture_generation, 'upsert', 'live',
                          {'id': 6}, {'id': 6, 'value': 'after-seal'})
    with pytest.raises(DBAPIError, match='MIRROR_COVERAGE_INVALID'):
        final_target.application.apply_batch(**final_target.request, records=[later_record],
                                             scan=AnchoredScan(data_end, data_end + 1, advanced, advanced, (data_end,)))
    current_authority = replace(final_target.authority, owner_epoch=final_target.authority.owner_epoch + 1)
    admin.execute('UPDATE source_mirror_state.mirrors SET authority = %s::jsonb WHERE id = %s',
                  (json.dumps(asdict(current_authority)), final_target.mirror))
    retry = SealedScan(data_end, data_end, data_bounds, data_bounds, (), data_end)
    with pytest.raises(DBAPIError, match='MIRROR_CONTROL_CONFLICT'):
        final_target.application.apply_batch(**final_target.request, records=[], scan=retry)
    with pytest.raises(DBAPIError, match='MIRROR_COVERAGE_INVALID'):
        final_target.application.apply_batch(**{**final_target.request, 'authority': current_authority},
                                             records=[], scan=retry)
    assert final_target.state() == sealed_target_state
    assert transport_state(probe, topics, quiesced=True) == sealed
    final_lineage, final_wal = source_position(probe, active=False)
    assert final_lineage == source_lineage and final_wal[:2] == quiesced_wal[:2]
    assert final_wal[2] - initial_wal[0] <= WAL_BUDGET
    assert time.monotonic() - quiescence_started <= 35
    print(f'seal source={source_lineage} initial_wal={initial_wal} before_stop_wal={before_stop_wal} '
          f'quiesced_wal={quiesced_wal} final_wal={final_wal} partition=0 transport={sealed}')
