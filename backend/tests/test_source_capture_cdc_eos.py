import json
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv('REFRAQ_CDC_EOS_TRIAL') != '1', reason='disposable Docker EOS trial only')


@pytest.fixture(scope='module')
def eos():
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
