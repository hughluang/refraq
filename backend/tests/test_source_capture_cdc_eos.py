import json
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv('REFRAQ_CDC_EOS_TRIAL') != '1', reason='disposable Docker EOS trial only')


@pytest.fixture(scope='module')
def eos():
    from backend.tests.cdc.eos import disposable_eos_profile

    with disposable_eos_profile() as profile:
        yield profile


@pytest.fixture
def isolated_eos():
    from backend.tests.cdc.eos import disposable_eos_profile

    with disposable_eos_profile() as profile:
        yield profile


def test_transaction_visibility_and_eof(eos):
    kafka = eos.kafka
    topic = 'transport-proof'
    kafka.create_topic(topic)
    identity = kafka.identity(topic)
    assert kafka.bounds(topic).positions == (0, 0, 0)
    assert kafka.scan(topic) == ([], 0)

    producer = kafka.transactional_producer()
    producer.begin_transaction()
    assert kafka.append(producer, topic, b'committed') == 0
    producer.commit_transaction(8)
    assert eos.log_batches(topic) == [(0, 0, 'DATA'), (1, 1, 'COMMIT')]
    assert kafka.bounds(topic).positions == (0, 2, 2)
    assert kafka.scan(topic) == ([(0, None, b'committed')], 2)

    producer.begin_transaction()
    assert kafka.append(producer, topic, b'aborted') == 2
    assert kafka.bounds(topic).positions == (0, 2, 3)
    assert kafka.scan(topic) == ([(0, None, b'committed')], 2)
    assert kafka.scan(topic, committed=False) == ([(0, None, b'committed'), (2, None, b'aborted')], 3)

    producer.abort_transaction(8)
    assert eos.log_batches(topic) == [(0, 0, 'DATA'), (1, 1, 'COMMIT'), (2, 2, 'DATA'), (3, 3, 'ABORT')]
    assert kafka.bounds(topic).positions == (0, 4, 4)
    assert kafka.scan(topic, start=1) == ([], 4)
    assert kafka.append(kafka.producer(), topic, b'anchor') == 4
    assert kafka.scan(topic) == ([(0, None, b'committed'), (4, None, b'anchor')], 5)
    assert kafka.scan(topic, committed=False) == (
        [(0, None, b'committed'), (2, None, b'aborted'), (4, None, b'anchor')], 5,
    )
    assert kafka.identity(topic) == identity


def test_prefix_loss_and_topic_recreation_are_visible_to_reader(eos):
    kafka = eos.kafka
    topic = 'transport-lineage'
    kafka.create_topic(topic)
    identity = kafka.identity(topic)
    producer = kafka.producer()
    assert kafka.append(producer, topic, b'lost') == 0
    assert kafka.append(producer, topic, b'retained') == 1
    assert kafka.scan(topic) == ([(0, None, b'lost'), (1, None, b'retained')], 2)

    assert kafka.delete_prefix(topic, before=1) == 1
    assert kafka.bounds(topic).positions == (1, 2, 2)
    assert kafka.identity(topic) == identity
    assert kafka.scan(topic, start=1) == ([(1, None, b'retained')], 2)

    kafka.delete_topic(topic)
    kafka.create_topic(topic)
    replacement = kafka.identity(topic)
    assert replacement[0] == identity[0] and replacement[1] != identity[1]
    assert kafka.bounds(topic).positions == (0, 0, 0)
    assert kafka.append(kafka.producer(), topic, b'new-zero') == 0
    assert kafka.append(kafka.producer(), topic, b'new-one') == 1
    assert kafka.bounds(topic).positions == (0, 2, 2)
    assert kafka.scan(topic) == ([(0, None, b'new-zero'), (1, None, b'new-one')], 2)


def test_source_offset_lineage_across_pre_and_post_commit_worker_crashes(eos):
    topic = 'trial.public.items'
    kafka = eos.kafka
    lineage = eos.source_lineage()
    initial_lsn = eos.confirmed_lsn()
    assert eos.sql("INSERT INTO items VALUES (7,'first') RETURNING id;") == '7'
    checkpoint = eos.await_checkpoint(initial_lsn)
    durable = eos.committed_source_offset()
    assert durable[1] == checkpoint[1]
    identity = kafka.identity(topic)
    offset_identity = kafka.identity('offsets')
    assert offset_identity[0] == identity[0]
    assert kafka.bounds(topic).positions == (0, 2, 2)
    first = _events(kafka.scan(topic), end=2)
    assert _changes(first) == [(0, 7, 'c', None, 'first')]

    with eos.arm_crash():
        assert eos.sql("UPDATE items SET value='second' WHERE id=7 RETURNING id;") == '7'
        eos.await_crash_boundary()
        assert kafka.bounds(topic).positions == (0, 2, 3)
        assert _events(kafka.scan(topic), end=2) == first
        pending = _events(kafka.scan(topic, committed=False), end=3)
        assert _changes(pending) == [(0, 7, 'c', None, 'first'), (2, 7, 'u', 'first', 'second')]
        assert eos.committed_source_offset() == durable
        assert eos.confirmed_lsn() == checkpoint[0]
        eos.kill_worker()

    assert eos.committed_source_offset() == durable
    eos.resume_worker()
    second_checkpoint = eos.await_checkpoint(*checkpoint)
    second_durable = eos.committed_source_offset()
    assert second_durable[0] > durable[0] and second_durable[1] == second_checkpoint[1]
    assert eos.source_lineage() == lineage
    assert kafka.identity(topic) == identity
    assert kafka.bounds(topic).positions == (0, 6, 6)
    assert eos.log_batches(topic) == [
        (0, 0, 'DATA'), (1, 1, 'COMMIT'), (2, 2, 'DATA'), (3, 3, 'ABORT'), (4, 4, 'DATA'), (5, 5, 'COMMIT'),
    ]
    recovered = _events(kafka.scan(topic), end=6)
    assert _changes(recovered) == [(0, 7, 'c', None, 'first'), (4, 7, 'u', 'first', 'second')]
    assert recovered[0] == first[0]
    assert recovered[1][1:] == pending[1][1:]

    eos.kill_worker()
    assert eos.committed_source_offset() == second_durable
    eos.resume_worker()
    assert eos.source_offset() == second_checkpoint[1]
    assert eos.committed_source_offset() == second_durable
    assert eos.confirmed_lsn() >= second_checkpoint[0]
    assert eos.source_lineage() == lineage
    assert eos.sql("INSERT INTO items VALUES (8,'resumed') RETURNING id;") == '8'
    final_checkpoint = eos.await_checkpoint(*second_checkpoint)
    final_durable = eos.committed_source_offset()
    assert final_durable[0] > second_durable[0] and final_durable[1] == final_checkpoint[1]
    assert kafka.identity(topic) == identity
    assert kafka.bounds(topic).positions == (0, 8, 8)
    assert eos.log_batches(topic)[-2:] == [(6, 6, 'DATA'), (7, 7, 'COMMIT')]
    final = _events(kafka.scan(topic), end=8)
    assert final[:2] == recovered
    assert _changes(final) == [
        (0, 7, 'c', None, 'first'), (4, 7, 'u', 'first', 'second'), (6, 8, 'c', None, 'resumed'),
    ]
    assert final[0][-1][0] < final[1][-1][0] < final[2][-1][0]
    assert kafka.identity('offsets') == offset_identity
    assert eos.source_lineage() == lineage


def test_source_eos_resumes_after_kafka_commit_before_slot_feedback(isolated_eos):
    eos = isolated_eos
    kafka = eos.kafka
    topic = 'trial.public.items'
    lineage = eos.source_lineage()
    initial_lsn = eos.confirmed_lsn()
    assert eos.sql("INSERT INTO items VALUES (7,'first') RETURNING id;") == '7'
    seed = eos.await_checkpoint(initial_lsn)
    seed_offset = eos.committed_source_offset()
    assert seed_offset == (0, seed[1])
    before_feedback = eos.slot_lsns(active=True)
    assert before_feedback[1] == seed[0]
    identities = kafka.identity(topic), kafka.identity('offsets')
    initial = _events(kafka.scan(topic), end=2)
    assert _changes(initial) == [(0, 7, 'c', None, 'first')]

    with eos.arm_crash():
        assert eos.sql("UPDATE items SET value='second' WHERE id=7 RETURNING id;") == '7'
        eos.await_crash_boundary()
        assert kafka.bounds(topic).positions == (0, 2, 3)
        assert _events(kafka.scan(topic), end=2) == initial
        pending = _events(kafka.scan(topic, committed=False), end=3)
        assert pending[:1] == initial
        assert _changes(pending[1:]) == [(2, 7, 'u', 'first', 'second')]
        assert eos.committed_source_offset() == seed_offset
        eos.disconnect_postgres()
        assert eos.slot_lsns(active=True) == before_feedback
        eos.release_crash_boundary()

        eos.wait('worker', lambda: all(kafka.bounds(name).positions[1] >= 4 for name in (topic, 'offsets')))
        assert kafka.bounds(topic).positions == (0, 4, 4)
        assert kafka.bounds('offsets').positions == (0, 4, 4)
        visible = _events(kafka.scan(topic), end=4)
        assert visible == pending
        durable = eos.committed_source_offset()
        assert durable[0] == 2
        assert before_feedback[1] < durable[1]['lsn_commit']
        assert durable[1]['lsn'] == visible[-1][-1][0] > before_feedback[1]
        assert eos.slot_lsns(active=True) == before_feedback, 'PostgreSQL received newer slot feedback before the cut'
        eos.kill_worker()

    assert eos.committed_source_offset() == durable
    eos.reconnect_postgres()
    assert eos.source_lineage() == lineage
    assert eos.slot_lsns(active=False) == before_feedback
    assert _events(kafka.scan(topic), end=4) == visible
    print(f'Kafka commit before feedback slot={before_feedback} Connect offsets={seed_offset}->{durable} '
          f'visible={_changes(visible)}')

    eos.resume_worker()
    assert eos.source_offset() == durable[1]
    assert eos.committed_source_offset() == durable
    assert eos.sql("INSERT INTO items VALUES (8,'resumed') RETURNING id;") == '8'
    final = eos.await_checkpoint(before_feedback[1], durable[1])
    final_offset = eos.committed_source_offset()
    assert final_offset == (4, final[1])
    assert final[0] >= durable[1]['lsn_commit']
    assert kafka.bounds(topic).positions == (0, 6, 6)
    records = _events(kafka.scan(topic), end=6)
    assert records[:2] == visible
    assert _changes(records[2:]) == [(4, 8, 'c', None, 'resumed')]
    assert records[-1][-1][0] == final_offset[1]['lsn'] > durable[1]['lsn']
    _assert_source_fault_logs(eos, topic)
    assert eos.sql('SELECT id, value FROM items ORDER BY id;') == '7|second\n8|resumed'
    assert (kafka.identity(topic), kafka.identity('offsets')) == identities
    assert eos.source_lineage() == lineage
    print(f'Kafka commit recovery slot={eos.slot_lsns(active=True)} Connect offset={final_offset} '
          f'visible={_changes(records)}')


def test_source_eos_resumes_after_postgres_crash_with_slot_rewind(isolated_eos):
    eos = isolated_eos
    kafka = eos.kafka
    topic = 'trial.public.items'
    lineage = eos.source_lineage()
    initial_lsn = eos.confirmed_lsn()
    assert eos.sql("INSERT INTO items VALUES (7,'first') RETURNING id;") == '7'
    seed = eos.await_checkpoint(initial_lsn)
    seed_offset = eos.committed_source_offset()
    assert seed_offset == (0, seed[1])
    assert _changes(_events(kafka.scan(topic), end=2)) == [(0, 7, 'c', None, 'first')]
    identities = kafka.identity(topic), kafka.identity('offsets')

    eos.sql('CHECKPOINT;')
    disk_checkpoint = eos.sql('SELECT checkpoint_lsn FROM pg_control_checkpoint();')
    persisted = eos.slot_lsns(active=True)
    assert persisted[1] == seed[0]

    assert eos.sql("UPDATE items SET value='second' WHERE id=7 RETURNING id;") == '7'
    settled = eos.await_checkpoint(*seed)
    durable = eos.committed_source_offset()
    assert durable == (2, settled[1])
    visible = _events(kafka.scan(topic), end=4)
    assert _changes(visible) == [(0, 7, 'c', None, 'first'), (2, 7, 'u', 'first', 'second')]
    assert persisted[1] < visible[-1][-1][0] == durable[1]['lsn']
    before_crash = eos.slot_lsns(active=True)
    assert before_crash[1] == settled[0]
    assert persisted[1] < durable[1]['lsn_commit'] <= before_crash[1]
    assert eos.sql('SELECT checkpoint_lsn FROM pg_control_checkpoint();') == disk_checkpoint

    eos.crash_postgres()
    eos.kill_worker()
    assert eos.committed_source_offset() == durable
    eos.resume_postgres()
    assert eos.source_lineage() == lineage
    rewound = eos.slot_lsns(active=False)
    assert rewound == persisted and rewound[1] < before_crash[1], 'PostgreSQL crash did not rewind the slot'
    assert eos.sql('SELECT value FROM items WHERE id=7;') == 'second'
    assert eos.committed_source_offset() == durable
    assert _events(kafka.scan(topic), end=4) == visible
    print(f'PostgreSQL crash checkpoint={disk_checkpoint} slot={persisted}->{before_crash}->{rewound} '
          f'Connect offsets={seed_offset}->{durable} visible={_changes(visible)}')

    eos.resume_worker()
    assert eos.source_offset() == durable[1]
    assert eos.committed_source_offset() == durable
    assert eos.sql("INSERT INTO items VALUES (8,'resumed') RETURNING id;") == '8'
    final = eos.await_checkpoint(*settled)
    final_offset = eos.committed_source_offset()
    assert final_offset == (4, final[1])
    assert kafka.bounds(topic).positions == (0, 6, 6)
    records = _events(kafka.scan(topic), end=6)
    assert records[:2] == visible
    assert _changes(records[2:]) == [(4, 8, 'c', None, 'resumed')]
    assert records[-1][-1][0] == final_offset[1]['lsn'] > durable[1]['lsn']
    _assert_source_fault_logs(eos, topic)
    assert eos.sql('SELECT id, value FROM items ORDER BY id;') == '7|second\n8|resumed'
    assert (kafka.identity(topic), kafka.identity('offsets')) == identities
    assert eos.source_lineage() == lineage
    print(f'PostgreSQL crash recovery slot={eos.slot_lsns(active=True)} Connect offset={final_offset} '
          f'visible={_changes(records)}')


def _assert_source_fault_logs(eos, topic):
    expected = [
        (0, 0, 'DATA'), (1, 1, 'COMMIT'), (2, 2, 'DATA'), (3, 3, 'COMMIT'), (4, 4, 'DATA'), (5, 5, 'COMMIT'),
    ]
    assert eos.log_batches(topic) == expected
    assert eos.log_batches('offsets') == expected


def _events(scan, *, end):
    records, eof = scan
    assert eof == end
    events = []
    for offset, key, value in records:
        envelope = json.loads(value)
        source = envelope['source']
        assert tuple(source[field] for field in ('version', 'name', 'db', 'schema', 'table')) == (
            '3.7.1.Final', 'trial', 'postgres', 'public', 'items',
        )
        evidence = (source['lsn'], source['txId'], json.loads(source['sequence']))
        assert evidence[0] > 0 and evidence[1] > 0 and evidence[2][1] == str(evidence[0])
        events.append((offset, json.loads(key), envelope['op'], envelope['before'], envelope['after'], evidence))
    return events


def _changes(events):
    return [
        (offset, key['id'], op, before and before['value'], after and after['value'])
        for offset, key, op, before, after, _ in events
    ]
