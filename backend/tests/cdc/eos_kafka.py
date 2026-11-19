import time
from contextlib import contextmanager
from dataclasses import dataclass

from confluent_kafka import (
    Consumer, IsolationLevel, KafkaError, KafkaException, Producer, TopicCollection, TopicPartition, libversion, version,
)
from confluent_kafka.admin import AdminClient, NewTopic, OffsetSpec

TIMEOUT = 8


@contextmanager
def kafka_errors():
    try:
        yield
    except KafkaException as error:
        raise AssertionError(f'Kafka operation failed (code={error.args[0].code()})') from None


@dataclass(frozen=True)
class Bounds:
    positions: tuple[int, int, int]
    epoch: int


class KafkaProbe:
    def __init__(self, root, address):
        assert version() == libversion()[0] == '2.13.2'
        self.config = {
            'bootstrap.servers': f'{address}:9094',
            'security.protocol': 'ssl',
            'ssl.ca.location': str(root / 'ca.pem'),
            'ssl.certificate.location': str(root / 'worker/cert.pem'),
            'ssl.key.location': str(root / 'worker/key.pem'),
            'ssl.endpoint.identification.algorithm': 'https',
            'socket.timeout.ms': 4000,
            'log_level': 0,
        }
        self.admin = AdminClient(self.config)

    def ready(self):
        with kafka_errors():
            try:
                cluster = self.admin.describe_cluster(request_timeout=2).result()
            except KafkaException as error:
                if error.args[0].code() == KafkaError._TIMED_OUT:
                    return False
                raise
        return bool(cluster.cluster_id and cluster.controller)

    def create_topic(self, topic):
        config = {'cleanup.policy': 'delete', 'retention.ms': '-1', 'retention.bytes': '-1'}
        with kafka_errors():
            self.admin.create_topics([NewTopic(topic, 1, 1, config=config)], request_timeout=TIMEOUT)[topic].result()
            deadline = time.monotonic() + TIMEOUT
            while (remaining := deadline - time.monotonic()) > 0:
                try:
                    desc = self._describe_topic(topic, remaining)
                    if len(desc.partitions) == 1 and desc.partitions[0].leader.id >= 0:
                        return
                except KafkaException as error:
                    if error.args[0].code() != KafkaError.UNKNOWN_TOPIC_OR_PART:
                        raise
                time.sleep(0.1)
        raise AssertionError('New Kafka topic metadata did not become visible')

    def delete_prefix(self, topic, *, before):
        partition = TopicPartition(topic, 0, before)
        with kafka_errors():
            return self.admin.delete_records([partition], request_timeout=TIMEOUT)[partition].result().low_watermark

    def delete_topic(self, topic):
        with kafka_errors():
            self.admin.delete_topics([topic], operation_timeout=TIMEOUT, request_timeout=TIMEOUT)[topic].result()

    def _describe_topic(self, topic, timeout):
        return self.admin.describe_topics(TopicCollection([topic]), request_timeout=timeout)[topic].result()

    def identity(self, topic):
        with kafka_errors():
            cluster = self.admin.describe_cluster(request_timeout=TIMEOUT).result()
            desc = self._describe_topic(topic, TIMEOUT)
        assert cluster.cluster_id and str(desc.topic_id) != 'AAAAAAAAAAAAAAAAAAAAAA'
        assert [partition.id for partition in desc.partitions] == [0]
        return cluster.cluster_id, str(desc.topic_id)

    def bounds(self, topic):
        partition = TopicPartition(topic, 0)
        query = (
            (OffsetSpec.earliest(), IsolationLevel.READ_COMMITTED),
            (OffsetSpec.latest(), IsolationLevel.READ_COMMITTED),
            (OffsetSpec.latest(), IsolationLevel.READ_UNCOMMITTED),
        )
        with kafka_errors():
            first, stable, high = (
                self.admin.list_offsets({partition: spec}, isolation_level=isolation,
                                        request_timeout=TIMEOUT)[partition].result()
                for spec, isolation in query
            )
        assert first.offset <= stable.offset <= high.offset
        assert high.leader_epoch == stable.leader_epoch >= 0
        return Bounds((first.offset, stable.offset, high.offset), high.leader_epoch)

    def scan(self, topic, *, start=0, committed=True):
        with kafka_errors():
            consumer = Consumer({
                **self.config,
                'group.id': 'eos-probe',
                'isolation.level': 'read_committed' if committed else 'read_uncommitted',
                'enable.auto.commit': False,
                'enable.auto.offset.store': False,
                'auto.offset.reset': 'error',
                'allow.auto.create.topics': False,
                'check.crcs': True,
                'enable.partition.eof': True,
                'queued.max.messages.kbytes': 1024,
                'fetch.max.bytes': 1024 * 1024,
            })
            try:
                consumer.assign([TopicPartition(topic, 0, start)])
                events = []
                deadline = time.monotonic() + TIMEOUT
                while time.monotonic() < deadline:
                    msg = consumer.poll(0.25)
                    if msg is None:
                        continue
                    assert (msg.topic(), msg.partition()) == (topic, 0)
                    error = msg.error()
                    if error is not None:
                        if error.code() == KafkaError._PARTITION_EOF:
                            return events, msg.offset()
                        raise KafkaException(error)
                    assert len(events) < 32
                    assert msg.offset() >= start and (not events or msg.offset() > events[-1][0])
                    events.append((msg.offset(), msg.key(), msg.value()))
                raise AssertionError('Kafka scan did not reach partition EOF')
            finally:
                consumer.close()

    def producer(self):
        with kafka_errors():
            return Producer({**self.config, 'acks': 'all', 'message.timeout.ms': 5000})

    def transactional_producer(self):
        with kafka_errors():
            producer = Producer({**self.config, 'transactional.id': 'transport-proof',
                                 'transaction.timeout.ms': 60000, 'message.timeout.ms': 5000})
            producer.init_transactions(TIMEOUT)
            return producer

    def append(self, producer, topic, value):
        results = []

        def delivery(error, message):
            results.append((error.code() if error else 0, message.offset()))

        with kafka_errors():
            producer.produce(topic, value=value, partition=0, on_delivery=delivery)
            assert producer.flush(TIMEOUT) == 0
        assert len(results) == 1 and results[0][0] == 0
        return results[0][1]
