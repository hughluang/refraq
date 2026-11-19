"""Measure a same-primary snapshot checkpoint and seal in the disposable EOS rig."""

import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from backend.tests.cdc.eos import CONNECTOR, EosTrial
from backend.tests.cdc.signal import EMPTY_TABLE, POPULATED_TABLE, SnapshotSignalProbe

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
            measure_seal(profile)
        finally:
            profile.clean()


def measure_seal(profile):
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
    assert transport_state(probe, topics, quiesced=True) == sealed
    final_lineage, final_wal = source_position(probe, active=False)
    assert final_lineage == source_lineage and final_wal[:2] == quiesced_wal[:2]
    assert final_wal[2] - initial_wal[0] <= WAL_BUDGET
    assert time.monotonic() - quiescence_started <= 35
    print(f'seal source={source_lineage} initial_wal={initial_wal} before_stop_wal={before_stop_wal} '
          f'quiesced_wal={quiesced_wal} final_wal={final_wal} partition=0 transport={sealed}')
