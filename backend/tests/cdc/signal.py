"""Native PostgreSQL signal and Kafka notification probe on the disposable CDC rig."""

import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime

from backend.tests.cdc.trial import PINS

SIGNAL_TABLE = 'public.snapshot_signal'
EMPTY_TABLE = 'public.signal_empty'
POPULATED_TABLE = 'public.signal_populated'
SCAN_BLOCKER_LOCK = f'''
    SELECT 1 FROM pg_locks JOIN pg_stat_activity USING (pid)
    WHERE relation = '{POPULATED_TABLE}'::regclass AND granted
        AND mode = 'AccessExclusiveLock' AND application_name = 'snapshot-blocker-fixture';
'''


def timestamp_ms(instant):
    return int(datetime.fromisoformat(instant).timestamp() * 1000)


FIXTURE = rf'''
CREATE TABLE {EMPTY_TABLE} (id int PRIMARY KEY);
CREATE TABLE {POPULATED_TABLE} (id int PRIMARY KEY, value text NOT NULL);
ALTER TABLE {POPULATED_TABLE} REPLICA IDENTITY FULL;
INSERT INTO {POPULATED_TABLE} VALUES (1, 'before-delete'), (2, 'before-update');
CREATE TABLE {SIGNAL_TABLE} (id varchar(64) PRIMARY KEY, type varchar(32), data varchar(2048));
CREATE TABLE snapshot_binding (operation uuid PRIMARY KEY, generation uuid NOT NULL, table_name text NOT NULL);
CREATE TABLE snapshot_scan_release (id int PRIMARY KEY);
SELECT format('GRANT SELECT ON {EMPTY_TABLE}, {POPULATED_TABLE}, {SIGNAL_TABLE} TO %I', rolname)
FROM pg_roles WHERE rolreplication AND NOT rolsuper \gexec
SELECT format('GRANT INSERT ON {SIGNAL_TABLE} TO %I', rolname)
FROM pg_roles WHERE rolreplication AND NOT rolsuper \gexec
'''


class SnapshotSignalProbe:
    def __init__(self, profile):
        self.profile = profile
        suffix = profile.prefix.removeprefix('refraq-')
        self.connector_path = f'connectors/snapshot-{suffix}'
        self.source = f'snapshot-source-{suffix}'
        self.slot = f'snapshot_{suffix}'
        self.publication = f'snapshot_pub_{suffix}'
        self.notifications = f'{self.source}.notifications'
        self.notification_offset = 0

    def configure(self):
        config = json.loads(self.profile.rest('connectors/trial/config'))
        config.pop('name', None)
        self.profile.rest('connectors/trial/stop', '-X', 'PUT')

        def stopped():
            return json.loads(self.profile.rest('connectors/trial/status'))['connector']['state'] == 'STOPPED'

        self.profile.wait('worker', stopped)
        self.profile.rest('connectors/trial', '-X', 'DELETE')
        self.profile.sql(FIXTURE + f'''
            CREATE PUBLICATION {self.publication} FOR TABLE {EMPTY_TABLE}, {POPULATED_TABLE}, {SIGNAL_TABLE};
            SELECT pg_create_logical_replication_slot('{self.slot}', 'pgoutput');
        ''')
        for topic in (self.notifications, self.topic(EMPTY_TABLE), self.topic(POPULATED_TABLE)):
            self.kafka('kafka-topics', '--create', '--topic', topic, '--partitions', '1',
                       '--replication-factor', '1', '--config', 'cleanup.policy=delete')
        config.update({
            'topic.prefix': self.source,
            'slot.name': self.slot,
            'publication.name': self.publication,
            'table.include.list': ','.join(map(re.escape, (EMPTY_TABLE, POPULATED_TABLE, SIGNAL_TABLE))),
            'signal.enabled.channels': 'source',
            'signal.data.collection': SIGNAL_TABLE,
            'incremental.snapshot.watermarking.strategy': 'insert_insert',
            'incremental.snapshot.chunk.size': '32',
            'notification.enabled.channels': 'sink',
            'notification.sink.topic.name': self.notifications,
        })
        self.profile.rest(f'{self.connector_path}/config', '-X', 'PUT', '-H', 'Content-Type: application/json',
                          '--data-binary', '@-', data=json.dumps(config))
        tls = self.await_stream()
        assert tls in ('TLSv1.2', 'TLSv1.3')
        print(f'pins={json.dumps(PINS, sort_keys=True)} PostgreSQL=18.6 pgoutput={tls} '
              f'Connect={self.profile.worker_version} Debezium=3.7.1.Final Kafka=4.3.1 '
              f'Connect_REST=mTLS Kafka=mTLS signal=source watermark=insert_insert notification=sink '
              f'connector_rest={self.connector_path} connector_name={self.source} rig={self.profile.prefix}')

    def await_stream(self):
        return self.await_sql(f'''
            SELECT version FROM pg_stat_ssl WHERE pid =
                (SELECT active_pid FROM pg_replication_slots WHERE slot_name = '{self.slot}' AND plugin = 'pgoutput') AND ssl;
        ''', 'No active pgoutput replication session over TLS', seconds=45)

    def topic(self, table):
        return f'{self.source}.{table}'

    def lineage(self):
        topics = (self.notifications, self.topic(EMPTY_TABLE), self.topic(POPULATED_TABLE))
        description = self.kafka('kafka-topics', '--describe', '--topic', '|'.join(map(re.escape, topics)))
        topic_ids = {}
        for topic in topics:
            topic_ids[topic], = re.findall(rf'Topic:\s+{re.escape(topic)}\s+TopicId:\s+(\S+)\s+PartitionCount:\s+1\b',
                                           description)
        publication_oid = self.profile.sql(f"SELECT oid FROM pg_publication WHERE pubname = '{self.publication}';")
        assert publication_oid.isdecimal()
        slot_identity = self.profile.exe('pg', 'sh', '-ec', f'stat -c %d:%i "$PGDATA/pg_replslot/{self.slot}"')
        print(f'lineage slot={self.slot} slot_identity={slot_identity} publication={self.publication} '
              f'publication_oid={publication_oid} kafka_topic_ids={json.dumps(topic_ids)} partition=0')
        return topic_ids, publication_oid, slot_identity

    def seed_live_stream(self, table):
        topic = self.topic(table)
        assert self.end(topic) == 0
        self.profile.sql(f"INSERT INTO {table} VALUES (4, 'live');")
        assert self.await_records(topic, 1) == 1
        records = self.read(topic, 0, 1)
        assert self.changes(table, records) == [(4, 'c', 'false', None, 'live')]
        lsn = int(records[0][2]['source']['lsn'])
        print(f'live_baseline topic={topic} partition=0 offset=0 op=c key=4 lsn={lsn}')
        return 1, lsn

    def kafka(self, tool, *args):
        return self.profile.exe('broker', f'/opt/kafka/bin/{tool}.sh', '--bootstrap-server', 'broker:9092',
                                '--command-config', '/trial/client', *args)

    def end(self, topic):
        result = self.kafka('kafka-get-offsets', '--topic', topic, '--time', 'latest')
        prefix = f'{topic}:0:'
        if not result.startswith(prefix) or not result.removeprefix(prefix).isdigit():
            raise AssertionError('Expected exactly one Kafka partition')
        return int(result.removeprefix(prefix))

    def await_records(self, topic, minimum):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            end = self.end(topic)
            if end >= minimum:
                return end
        raise AssertionError(f'Timed out waiting for {minimum} offsets on {topic}')

    def read(self, topic, first, end):
        count = end - first
        assert 0 < count <= 64
        raw = self.kafka('kafka-console-consumer', '--topic', topic, '--partition', '0', '--offset', str(first),
                         '--max-messages', str(count), '--timeout-ms', '10000',
                         '--formatter-property', 'print.offset=true', '--formatter-property', 'print.key=true')
        records = []
        for line in raw.splitlines():
            offset, key, value = line.split('\t')
            records.append((int(offset.removeprefix('Offset:')), json.loads(key), json.loads(value)))
        assert [offset for offset, _, _ in records] == list(range(first, end))
        return records

    def submit(self, table, *, lose_response=False):
        assert table in (EMPTY_TABLE, POPULATED_TABLE)
        operation, generation = uuid.uuid4(), uuid.uuid4()
        self.profile.sql(f"INSERT INTO snapshot_binding VALUES ('{operation}', '{generation}', '{table}');")
        insert = self.signal_insert(operation, table)
        if lose_response:
            assert self.profile.sql(f'BEGIN; {insert} COMMIT; SELECT 1 / 0;', check=False) is None
        else:
            assert self.profile.sql(insert) == str(operation)
        assert self.receipt(operation, table) == str(generation)
        return str(operation)

    def signal_insert(self, operation, table):
        payload = json.dumps({'type': 'incremental', 'data-collections': [re.escape(table)]})
        return (f"INSERT INTO {SIGNAL_TABLE} VALUES ('{operation}', 'execute-snapshot', '{payload}') "
                'ON CONFLICT (id) DO NOTHING RETURNING id;')

    def receipt(self, operation, table):
        generation, bound_table, kind, payload, observed_ms = self.profile.sql(f'''
            SELECT generation, table_name, type, data, floor(extract(epoch FROM clock_timestamp()) * 1000)
            FROM snapshot_binding
            JOIN {SIGNAL_TABLE} ON id = operation::text WHERE operation = '{operation}';
        ''').split('|')
        assert (bound_table, kind) == (table, 'execute-snapshot')
        assert json.loads(payload) == {'type': 'incremental', 'data-collections': [re.escape(table)]}
        print(f'receipt operation={operation} fixture_generation={generation} table={table} '
              f'type={kind} payload={payload} observed_ms={observed_ms}')
        return generation

    def retry_submission(self, operation, table):
        generation = self.receipt(operation, table)
        applied = self.profile.sql(self.signal_insert(operation, table)) == operation
        assert self.receipt(operation, table) == generation
        print(f'reissue operation={operation} fixture_generation={generation} appended={applied}')
        return applied

    def terminal_notifications(self, operation, table, status, rows, *, restart_offset=None):
        decisive = []
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            end = self.end(self.notifications)
            if end == self.notification_offset:
                continue
            for offset, key, value in self.read(self.notifications, self.notification_offset, end):
                data = value['additional_data']
                assert data['connector_name'] == self.source
                kind, timestamp = value['type'], int(value['timestamp'])
                if value['aggregate_type'] == 'Initial Snapshot':
                    assert kind == 'SKIPPED' and (offset == 0 or (
                        restart_offset is not None and offset >= restart_offset
                    ))
                    print(f'bootstrap aggregate=Initial_Snapshot offset={offset} type={kind} timestamp_ms={timestamp}')
                    continue
                assert key == {'id': operation}
                assert value['id'] == operation and value['aggregate_type'] == 'Incremental Snapshot'
                if kind in ('STARTED', 'DATA_COLLECTIONS_RESOLVED'):
                    assert data['data_collections'] == table
                elif kind == 'IN_PROGRESS':
                    assert data['current_collection_in_progress'] == table
                    print(f'notification operation={operation} connector_name={self.source} partition=0 offset={offset} '
                          f'type={kind} timestamp_ms={timestamp} table={table}')
                    continue
                elif kind == 'TABLE_SCAN_COMPLETED':
                    assert data['scanned_collection'] == table
                    assert (data['status'], int(data['total_rows_scanned'])) == (status, rows)
                else:
                    assert kind == 'COMPLETED'
                if restart_offset is not None and kind in ('TABLE_SCAN_COMPLETED', 'COMPLETED'):
                    assert offset >= restart_offset, f'{kind} was already present before restart at offset {offset}'
                decisive.append((kind, timestamp))
                scan = f' table={table} status={status} rows={rows}' if kind == 'TABLE_SCAN_COMPLETED' else ''
                print(f'notification operation={operation} connector_name={self.source} partition=0 offset={offset} '
                      f'type={kind} timestamp_ms={timestamp}{scan}')
            self.notification_offset = end
            if decisive and decisive[-1][0] == 'COMPLETED':
                kinds = [kind for kind, _ in decisive]
                beginning = ['STARTED', 'DATA_COLLECTIONS_RESOLVED']
                assert kinds[:-2] == beginning or (restart_offset is not None and kinds[:-2] == beginning * 2), kinds
                assert kinds[-2:] == ['TABLE_SCAN_COMPLETED', 'COMPLETED']
                assert [stamp for _, stamp in decisive] == sorted(stamp for _, stamp in decisive)
                return dict(decisive)
        raise AssertionError('Timed out waiting for aggregate COMPLETED')

    def verify_terminal_watermark(self, operation, table, decisive, closed_windows):
        marker_count, final_close = self.await_sql(f'''
            SELECT count(*), max(data::jsonb->>'closeWindowTimestamp') FROM {SIGNAL_TABLE}
            WHERE type = 'snapshot-window-close' AND data::jsonb->>'correlationId' = '{operation}'
                AND data::jsonb->>'dataCollectionId' = '{table}'
            HAVING count(*) >= {closed_windows};
        ''', 'No committed final close watermark for the completed table').split('|')
        assert int(marker_count) == closed_windows
        final_close_ms = timestamp_ms(final_close)
        assert decisive['COMPLETED'] <= final_close_ms
        print(f'terminal_watermark operation={operation} table={table} closed_windows={marker_count} '
              f'completed_ms={decisive["COMPLETED"]} final_close_ms={final_close_ms}')

    @contextmanager
    def blocked_scan(self, dml=''):
        with ThreadPoolExecutor(max_workers=1) as executor:
            transaction = executor.submit(self.profile.sql, f'''
                SET application_name = 'snapshot-blocker-fixture';
                SET statement_timeout = '25s';
                BEGIN;
                LOCK TABLE {POPULATED_TABLE} IN ACCESS EXCLUSIVE MODE;
                DO $$ BEGIN
                    WHILE NOT EXISTS (SELECT FROM snapshot_scan_release WHERE id = 1) LOOP
                        PERFORM pg_sleep(0.05);
                    END LOOP;
                END $$;
                {dml}
                COMMIT;
            ''')
            try:
                self.await_sql(SCAN_BLOCKER_LOCK, 'Scan blocker did not acquire the table lock')
                yield
            finally:
                self.profile.sql('INSERT INTO snapshot_scan_release VALUES (1);')
                transaction.result(timeout=10)

    def change_while_scan_blocked(self):
        with self.blocked_scan(f'''
            DELETE FROM {POPULATED_TABLE} WHERE id = 1;
            UPDATE {POPULATED_TABLE} SET value = 'updated' WHERE id = 2;
            INSERT INTO {POPULATED_TABLE} VALUES (3, 'inserted');
        '''):
            operation = self.submit(POPULATED_TABLE)
            chunk = self.await_open_window(operation)
        return operation, chunk

    def await_open_window(self, operation):
        chunk = self.await_sql(f'''
            SELECT marker.id FROM {SIGNAL_TABLE} AS marker
            WHERE marker.type = 'snapshot-window-open' AND marker.data::jsonb->>'correlationId' = '{operation}'
                AND marker.data::jsonb->>'dataCollectionId' = '{POPULATED_TABLE}'
                AND EXISTS (
                    SELECT FROM pg_locks AS waiter JOIN pg_stat_activity AS reader ON reader.pid = waiter.pid
                    JOIN pg_roles AS role ON role.oid = reader.usesysid
                    JOIN pg_stat_activity AS blocker ON blocker.pid = ANY(pg_blocking_pids(waiter.pid))
                    WHERE waiter.relation = '{POPULATED_TABLE}'::regclass AND NOT waiter.granted
                        AND role.rolreplication AND NOT role.rolsuper
                        AND blocker.application_name = 'snapshot-blocker-fixture'
                );
        ''', 'No committed open watermark with a connector scan waiting on the fixture lock')
        assert re.fullmatch(r'[0-9a-f-]+-open', chunk)
        chunk = chunk.removesuffix('-open')
        assert self.profile.sql(f"SELECT count(*) FROM {SIGNAL_TABLE} WHERE id = '{chunk}-close';") == '0'
        return chunk

    def await_checkpoint(self, minimum_lsn):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            offsets = json.loads(self.profile.rest(f'{self.connector_path}/offsets'))['offsets']
            confirmed = self.profile.sql(f"SELECT confirmed_flush_lsn FROM pg_replication_slots "
                                         f"WHERE slot_name = '{self.slot}';")
            high, low = (int(part, 16) for part in confirmed.split('/'))
            if offsets:
                offset, = offsets
                assert offset['partition'] == {'server': self.source}
                if offset['offset']['lsn'] >= minimum_lsn and (high << 32 | low) >= minimum_lsn:
                    print(f'checkpoint partition={offset["partition"]} stored_lsn={offset["offset"]["lsn"]} '
                          f'confirmed_flush_lsn={confirmed} minimum_lsn={minimum_lsn}')
                    return
            time.sleep(0.5)
        raise AssertionError(f'No stored Connect offset and slot confirmation for LSN {minimum_lsn}')

    def kill_worker(self, operation, chunk):
        worker = self.profile.prefix + 'worker'
        self.profile.docker('kill', '--signal', 'KILL', worker)
        assert self.profile.docker('inspect', '-f', '{{.State.ExitCode}}', worker) == '137'
        self.await_sql(f"SELECT 1 FROM pg_replication_slots WHERE slot_name = '{self.slot}' AND NOT active;",
                       'Source slot stayed active after killing the worker')
        assert self.profile.sql(SCAN_BLOCKER_LOCK) == '1', 'Scan blocker released its lock before the worker stopped'
        assert self.profile.sql(f"SELECT count(*) FROM {SIGNAL_TABLE} WHERE id = '{chunk}-close';") == '0'
        print(f'worker_killed operation={operation} chunk={chunk} committed_open=true committed_close=false')

    def start_worker(self):
        self.profile.docker('start', self.profile.prefix + 'worker')
        self.profile.wait('worker', lambda: self.profile.rest('', check=False))
        assert self.await_stream() in ('TLSv1.2', 'TLSv1.3')

    def verify_restart_stream(self, live_end):
        topic = self.topic(POPULATED_TABLE)
        self.profile.sql(f"UPDATE {POPULATED_TABLE} SET value = 'after-restart' WHERE id = 4;")
        end = self.await_records(topic, live_end + 4)
        records = self.read(topic, live_end, end)
        changes = self.changes(POPULATED_TABLE, records)
        print(f'restart_events topic={topic} partition=0 first={live_end} end={end} changes={changes}')
        assert changes == [
            (1, 'r', 'incremental', None, 'before-delete'),
            (2, 'r', 'incremental', None, 'before-update'),
            (4, 'r', 'incremental', None, 'live'),
            (4, 'u', 'false', 'live', 'after-restart'),
        ]

    def await_sql(self, statement, failure, seconds=10):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = self.profile.sql(statement)
            if value:
                return value
            time.sleep(0.1)
        raise AssertionError(failure)

    def changes(self, table, records):
        changes = []
        for _, key, value in records:
            source = value['source']
            assert (source['name'], source['schema'], source['table']) == (self.source, *table.split('.'))
            before, after = value['before'], value['after']
            changes.append((key['id'], value['op'], source['snapshot'],
                            before and before['value'], after and after['value']))
        return changes

    def verify_interleaving(self, operation, chunk, decisive, live_end):
        topic = self.topic(POPULATED_TABLE)
        end = self.await_records(topic, live_end + 4)
        records = self.read(topic, live_end, end)
        changes = self.changes(POPULATED_TABLE, records)
        print(f'chunk_events topic={topic} partition=0 first={live_end} end={end} changes={changes}')
        assert changes == [
            (1, 'd', 'false', 'before-delete', None),
            (2, 'u', 'false', 'before-update', 'updated'),
            (3, 'c', 'false', None, 'inserted'),
            (4, 'r', 'incremental', None, 'live'),
        ]
        commit, = {int(value['source']['ts_ms']) for _, _, value in records if value['op'] in ('c', 'u', 'd')}
        open_marker, close_marker = [json.loads(line) for line in self.profile.sql(f'''
            SELECT data FROM {SIGNAL_TABLE} WHERE id IN ('{chunk}-open', '{chunk}-close') ORDER BY type DESC;
        ''').splitlines()]
        for marker in (open_marker, close_marker):
            assert (marker['correlationId'], marker['dataCollectionId']) == (operation, POPULATED_TABLE)
        assert open_marker['openWindowTimestamp'] == close_marker['openWindowTimestamp']
        opened = timestamp_ms(open_marker['openWindowTimestamp'])
        closed = timestamp_ms(close_marker['closeWindowTimestamp'])
        assert decisive['STARTED'] <= opened < commit <= closed <= decisive['TABLE_SCAN_COMPLETED']
        print(f'concurrent_dml operation={operation} table={POPULATED_TABLE} chunk={chunk} '
              f'open_ms={opened} dml_commit_ms={commit} close_ms={closed} '
              f'data_partition=0 dml_offsets={live_end},{live_end + 1},{live_end + 2} '
              'incremental_reads=1 scan_waited_for_dml=true close_absent_before_release=true')
