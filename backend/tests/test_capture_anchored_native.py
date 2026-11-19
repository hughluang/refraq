"""Exercise sparse Kafka EOS delivery against the restricted PostgreSQL writer."""

from contextlib import contextmanager
from dataclasses import asdict, replace
import json
import os
from secrets import token_hex
from time import monotonic

from confluent_kafka import Consumer, TopicPartition
import psycopg
from psycopg import sql
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError

from backend.metadata.capture.decoder import PostgreSQLDecoder
from backend.metadata.capture.delivery import DeliveryBinding, DeliveryLimits, KafkaDelivery, KafkaIdentity
from backend.metadata.capture.runtime_store import RuntimeBlocked
from backend.metadata.capture.test_delivery import KEY, SCHEMA, envelope, wire_key
from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.bootstrap import create_generation, install
from backend.metadata.mirrors.types import AnchoredProfile, AnchoredScan, Authority, PartitionIdentity, ReadCommittedBounds
from backend.tests.cdc.eos import disposable_eos_profile


pytestmark = pytest.mark.skipif(os.getenv('REFRAQ_CDC_EOS_TRIAL') != '1', reason='disposable Docker EOS trial only')


@contextmanager
def disposable_target(eos):
    target_db = 'anchored_mirror'
    address = json.loads(eos.docker('inspect', '-f', '{{json .NetworkSettings.Networks}}',
                                   eos.prefix+'pg'))[eos.prefix]['IPAddress']
    hba = eos.root / 'pg/hba'
    hba.chmod(0o644)
    with hba.open('a') as handle:
        handle.write(f'hostssl {target_db} postgres,refraq_mirror_applier all scram-sha-256\n')
    hba.chmod(0o444)
    eos.sql(f'CREATE DATABASE {target_db};\nSELECT pg_reload_conf();')
    options = dict(host='pg', hostaddr=address, dbname=target_db, sslmode='verify-full',
                   sslrootcert=str(eos.root / 'ca.pem'), connect_timeout=4, options='-c statement_timeout=4000')
    with psycopg.connect(**options, user='postgres', password=(eos.root / 'pg/bootstrap').read_text(),
                         autocommit=True) as admin:
        install(admin)
        password = token_hex(32)
        admin.execute(sql.SQL('ALTER ROLE refraq_mirror_applier PASSWORD {}').format(sql.Literal(password)))
        engine = create_engine('postgresql+psycopg://', creator=lambda: psycopg.connect(
            **options, user='refraq_mirror_applier', password=password))
        try:
            yield admin, engine
        finally:
            engine.dispose()


def test_anchored_prefix_reaches_native_target():
    with disposable_eos_profile() as eos, disposable_target(eos) as (admin, engine):
        kafka = eos.kafka
        topic = 'anchored-coverage'
        kafka.create_topic(topic)
        cluster_id, topic_id = kafka.identity(topic)
        bounds = kafka.bounds(topic)
        assert bounds.positions == (0, 0, 0)
        profile = AnchoredProfile(leader_epoch=bounds.epoch)
        epoch = 'history-epoch'
        authority = Authority('source', 'binding', 1, 'runtime', 1, 1, 'capture')
        generation = 'a' * 32
        partition = PartitionIdentity(cluster_id, topic_id, 0)
        binding = DeliveryBinding(authority, generation, partition, topic)
        decoder = PostgreSQLDecoder(table_identity='table', capture_generation='capture', database='db',
                                    namespace='cap', schema_name='public', table_name='items',
                                    connector_version='3.7.1.Final', key_schema=KEY, value_schema=SCHEMA)
        create_generation(
            admin, mirror_id='mir_' + 'b' * 32, generation_id=generation, authority=authority, table_identity='table',
            history_epoch=epoch, operation_id='op', schema_fingerprint='schema',
            columns={'id': 'integer', 'body': 'text'}, key_columns=('id',), partition_identity=partition,
            start_offset=-1,
        )
        table = admin.execute('SELECT table_name FROM source_mirror_state.generations WHERE id = %s',
                              (generation,)).fetchone()[0]

        @contextmanager
        def admission(**request):
            assert request['binding'] == binding
            eos.check_storage()
            yield

        group = 'anchored-delivery'

        def reader(*, anchored=None):
            limits = DeliveryLimits(poll_seconds=2)
            return KafkaDelivery(
                consumer=Consumer({**kafka.config, 'group.id': group, 'isolation.level': 'read_committed',
                                   'enable.auto.commit': False, 'enable.auto.offset.store': False,
                                   'auto.offset.reset': 'error', 'allow.auto.create.topics': False,
                                   'check.crcs': True, 'enable.partition.eof': False,
                                   'queued.max.messages.kbytes': limits.queue_kbytes,
                                   'fetch.message.max.bytes': limits.max_record_bytes,
                                   'fetch.max.bytes': limits.max_batch_bytes}),
                identity=KafkaIdentity(kafka.admin), application=Application(engine), binding=binding,
                decoder=decoder, admission=admission, limits=limits,
                anchored_profile=anchored,
            )

        def ack(delivery):
            return delivery.consumer.committed([TopicPartition(topic, 0)], timeout=5)[0].offset

        def effects():
            return admin.execute(sql.SQL('SELECT id, body FROM source_mirror.{} ORDER BY id').format(
                sql.Identifier(table))).fetchall()

        def state():
            return admin.execute('SELECT applied_offset, anchored_coverage FROM source_mirror_state.generations '
                                 'WHERE id = %s', (generation,)).fetchone()

        def history():
            return admin.execute("SELECT commit_seq, entry_seq, before_image->>'body', after_image->>'body' "
                                 'FROM source_mirror_state.live_log ORDER BY commit_seq, entry_seq').fetchall()

        target = Application(engine)
        request = dict(authority=authority, generation_id=generation, partition_identity=partition)
        payload = envelope('u', body='would roll back')
        payload['payload']['source']['version'] = '3.7.1.Final'
        record = decoder.decode(offset=2, key=wire_key(), value=json.dumps(payload).encode())
        assert target.apply_batch(**request, records=[]) == {'offset': -1, 'commit_seq': 0}
        with pytest.raises(DBAPIError, match='MIRROR_DELIVERY_GAP'):
            target.apply_batch(**request, records=[record])

        producer = kafka.transactional_producer()

        def write(body, *, abort=False):
            payload = envelope('u', body=body)
            payload['payload']['source']['version'] = '3.7.1.Final'
            offsets = []

            def delivered(error, message):
                assert error is None
                offsets.append(message.offset())

            producer.begin_transaction()
            producer.produce(topic, partition=0, key=wire_key(), value=json.dumps(payload).encode(),
                             on_delivery=delivered)
            assert producer.flush(8) == 0
            if abort:
                producer.abort_transaction(8)
            else:
                producer.commit_transaction(8)
            return offsets

        assert write('aborted prefix', abort=True) == [0]
        assert write('first') == [2]
        assert write('second') == [4]
        assert eos.log_batches(topic) == [(0, 0, 'DATA'), (1, 1, 'ABORT'), (2, 2, 'DATA'),
                                          (3, 3, 'COMMIT'), (4, 4, 'DATA'), (5, 5, 'COMMIT')]
        strict = reader()
        try:
            with pytest.raises(RuntimeBlocked):
                strict.poll_once()
            assert ack(strict) == -1001
        finally:
            strict.close()

        with engine.begin() as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.connection.driver_connection.execute('SELECT * FROM source_mirror_state.generations')
        assert admin.execute('UPDATE source_mirror_state.generations SET anchored_profile = %s::jsonb '
                             'WHERE id = %s AND applied_offset = -1 AND anchored_profile IS NULL',
                             (json.dumps(asdict(profile)), generation)).rowcount == 1
        with pytest.raises(DBAPIError, match='permission denied for function apply_batch'):
            target.apply_batch(**request, records=[], anchored_profile=profile)
        admin.execute('GRANT EXECUTE ON FUNCTION source_mirror_state.apply_batch(jsonb,text,jsonb,jsonb,jsonb,jsonb) '
                      'TO refraq_mirror_applier')
        with pytest.raises(DBAPIError, match='MIRROR_COVERAGE_PROFILE_MISMATCH'):
            target.apply_batch(**request, records=[])

        delivery = reader(anchored=profile)
        consumer = delivery.consumer
        ack_attempts = []

        class UnconfirmedAck:
            def __getattr__(self, name):
                return getattr(consumer, name)

            def commit(self, *, offsets, asynchronous):
                ack_attempts.append((asynchronous, [item.offset for item in offsets], state(), effects(), history()))
                raise RuntimeError('injected ack failure after target commit')

        delivery.consumer = UnconfirmedAck()
        try:
            with pytest.raises(RuntimeBlocked):
                delivery.poll_once()
            applied, proof = state()
            assert applied == 4 and proof['offsets'] == [2, 4]
            assert proof['start'] == 0 and proof['end'] == 5 and proof['authority'] == asdict(authority)
            assert ack_attempts == [(
                False, [5], (4, proof), [(1, 'second')], [(1, 1, None, 'first'), (1, 2, 'first', 'second')],
            )]
            assert ack(delivery) == -1001
            assert effects() == [(1, 'second')]
            assert history() == [(1, 1, None, 'first'), (1, 2, 'first', 'second')]
        finally:
            delivery.close()

        assert write('aborted suffix', abort=True) == [6]
        restarted = reader(anchored=profile)
        try:
            assert restarted.poll_once() == 0
            assert state() == (4, proof) and ack(restarted) == -1001
            assert write('third') == [8]
            deadline = monotonic() + 12
            while restarted.poll_once() == 0:
                assert state() == (4, proof) and ack(restarted) == -1001
                assert monotonic() < deadline, 'Committed anchor did not become visible'
            assert ack(restarted) == 9 and state()[0] == 8
            assert effects() == [(1, 'third')]
            assert history() == [(1, 1, None, 'first'), (1, 2, 'first', 'second'), (2, 1, 'second', 'third')]
            retained = state()
            retained_history = history()
            assert retained[1]['start'] == 5 and retained[1]['end'] == 9 and retained[1]['offsets'] == [8]

            observed = ReadCommittedBounds(0, 10, 10, profile.leader_epoch)
            record = replace(record, offset=9)
            request['anchored_profile'] = profile
            with pytest.raises(DBAPIError, match='MIRROR_COVERAGE_INVALID'):
                target.apply_batch(**request, records=[record], scan=AnchoredScan(0, 10, observed, observed, (9,)))
            assert state() == retained and effects() == [(1, 'third')] and history() == retained_history
            with pytest.raises(DBAPIError, match='MIRROR_ENVELOPE_INVALID'):
                target.apply_batch(**request, records=[record, replace(record, offset=11, table_identity='other')],
                                   scan=AnchoredScan(9, 12, replace(observed, stable=12, high=12),
                                                     replace(observed, stable=12, high=12), (9, 11)))
            assert state() == retained and effects() == [(1, 'third')] and history() == retained_history
            assert target.apply_batch(**request, records=[]) == {'offset': 8, 'commit_seq': 2}

            wrong_epoch = replace(profile, leader_epoch=profile.leader_epoch + 1)
            with pytest.raises(DBAPIError, match='MIRROR_COVERAGE_PROFILE_MISMATCH'):
                target.apply_batch(**{**request, 'anchored_profile': wrong_epoch}, records=[])
            with pytest.raises(RuntimeBlocked, match='^delivery_anchored_lineage_mismatch$'):
                restarted.identity.read_committed_bounds(binding, wrong_epoch, restarted.limits.metadata_seconds)

            assert kafka.delete_prefix(topic, before=10) == 10
            with pytest.raises(RuntimeBlocked, match='^delivery_anchored_lineage_mismatch$'):
                restarted.identity.read_committed_bounds(binding, profile, restarted.limits.metadata_seconds)
            with pytest.raises(RuntimeBlocked):
                restarted.poll_once()
            kafka.delete_topic(topic)
            kafka.create_topic(topic)
            replacement = kafka.producer()
            for offset in range(10):
                assert kafka.append(replacement, topic, b'recreated') == offset
            assert kafka.bounds(topic).positions == (0, 10, 10)
            with pytest.raises(RuntimeBlocked, match='^delivery_partition_identity_mismatch$'):
                restarted.identity.verify(binding, restarted.limits.metadata_seconds)
            with pytest.raises(RuntimeBlocked):
                restarted.poll_once()
            assert state() == retained and effects() == [(1, 'third')]
            assert history() == retained_history
        finally:
            restarted.close()
