"""Independent bounded Kafka-to-Application delivery, with target-owned progress.

``open_delivery`` is the production composition entry. It never subscribes to a
consumer-group cursor. The caller supplies a current admission context manager
which retains authority/exclusion locks through target commit and Kafka ack.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import logging
import math
from threading import Event

from confluent_kafka import Consumer, TopicCollection, TopicPartition
from confluent_kafka.admin import AdminClient

from backend.metadata.capture.runtime_store import RuntimeBlocked
from backend.metadata.mirrors.application import Application
from backend.metadata.mirrors.types import Authority, PartitionIdentity


@dataclass(frozen=True)
class DeliveryBinding:
    authority: Authority
    generation_id: str
    partition_identity: PartitionIdentity
    topic: str

    def validate(self, decoder):
        a, p = self.authority, self.partition_identity
        if (not isinstance(a, Authority) or not isinstance(p, PartitionIdentity)
                or not all(isinstance(v, str) and v for v in (
                    a.source_id, a.resource_binding_id, a.runtime_instance_id,
                    a.capture_generation, self.generation_id, p.runtime_cluster_id,
                    p.topic_incarnation_id, self.topic,
                ))
                or any(type(v) is not int or v < 1 for v in (
                    a.owner_epoch, a.control_revision, a.credential_revision,
                ))
                or type(p.partition) is not int or p.partition < 0
                or a.capture_generation != decoder.capture_generation):
            raise RuntimeBlocked("delivery_binding_invalid")


@dataclass(frozen=True)
class DeliveryLimits:
    max_records: int = 100
    max_batch_bytes: int = 1048576
    max_record_bytes: int = 262144
    poll_seconds: float = 1.0
    metadata_seconds: float = 5.0
    retry_seconds: float = 5.0
    queue_kbytes: int = 2048

    def validate(self):
        if (type(self.max_records) is not int or not 1 <= self.max_records <= 1000
                or type(self.max_record_bytes) is not int
                or type(self.max_batch_bytes) is not int
                or not 1 <= self.max_record_bytes <= self.max_batch_bytes <= 16777216
                or type(self.queue_kbytes) is not int
                or not 1 <= self.queue_kbytes <= 16384
                or any(type(v) not in {int, float} or not math.isfinite(v)
                       for v in (self.poll_seconds, self.metadata_seconds, self.retry_seconds))
                or not 0 < self.poll_seconds <= 10
                or not 0 < self.metadata_seconds <= 30
                or not 0 < self.retry_seconds <= 300):
            raise RuntimeBlocked("delivery_capacity_invalid")


class KafkaIdentity:
    """Read real broker cluster and immutable topic ids, never names as ids."""

    def __init__(self, admin):
        self.admin = admin

    def verify(self, binding, timeout):
        cluster = self.admin.describe_cluster(request_timeout=timeout).result(timeout=timeout)
        topic = self.admin.describe_topics(
            TopicCollection([binding.topic]), request_timeout=timeout,
        )[binding.topic].result(timeout=timeout)
        p = binding.partition_identity
        if (cluster.cluster_id != p.runtime_cluster_id
                or str(topic.topic_id) != p.topic_incarnation_id
                or {part.id for part in topic.partitions} != {p.partition}):
            # This profile requires a sole table partition: key changes cannot
            # be ordered safely across independently consumed partitions.
            raise RuntimeBlocked("delivery_partition_identity_mismatch")


class KafkaDelivery:
    def __init__(self, *, consumer, identity, application, binding, decoder,
                 admission, limits=DeliveryLimits()):
        limits.validate()
        binding.validate(decoder)
        if not callable(admission):
            raise RuntimeBlocked("delivery_admission_required")
        self.consumer = consumer
        self.identity = identity
        self.application = application
        self.binding = binding
        self.decoder = decoder
        self.admission = admission
        self.limits = limits
        self.stopping = Event()
        self.closed = False

    def _apply(self, records):
        b = self.binding
        coverage = self.application.apply_batch(
            authority=b.authority, generation_id=b.generation_id,
            partition_identity=b.partition_identity, records=records,
        )
        offset = coverage.get("offset")
        if type(offset) is not int or offset < -1:
            raise RuntimeBlocked("delivery_coverage_invalid")
        return offset

    def poll_once(self):
        """Apply at most one bounded batch; any failure requires target reseek.

        admission(binding=..., decoder=..., limits=...) must yield None only
        after validating current management authority, source/profile readiness,
        installed generation schema/key mapping, capacity and owner exclusion.
        It must hold the relevant authority locks until the context exits.
        There is deliberately no permissive default or boolean evidence path.
        """
        if self.closed or self.stopping.is_set():
            return 0
        assigned = False
        try:
            with self.admission(binding=self.binding, decoder=self.decoder, limits=self.limits) as permit:
                if permit is not None:
                    raise RuntimeBlocked("delivery_admission_invalid")
                self.identity.verify(self.binding, self.limits.metadata_seconds)
                # Empty batches exercise the same target authority fence and
                # return committed coverage without mutating rows or the log.
                applied = self._apply([])
                b = self.binding
                partition = TopicPartition(b.topic, b.partition_identity.partition, applied + 1)
                self.consumer.assign([partition])
                assigned = True
                low, high = self.consumer.get_watermark_offsets(
                    partition, timeout=self.limits.metadata_seconds, cached=False,
                )
                if not low <= applied + 1 <= high:
                    raise RuntimeBlocked("delivery_coverage_unavailable")
                records, size = [], 0
                while len(records) < self.limits.max_records and not self.stopping.is_set():
                    # Reserve a complete maximum-sized record before polling.
                    if size + self.limits.max_record_bytes > self.limits.max_batch_bytes:
                        break
                    message = self.consumer.poll(self.limits.poll_seconds if not records else 0)
                    if message is None:
                        break
                    if message.error():
                        raise RuntimeBlocked("delivery_poll_unavailable")
                    if (message.topic() != b.topic
                            or message.partition() != b.partition_identity.partition
                            or message.offset() != applied + len(records) + 1):
                        # read_committed hides control/aborted records; compaction
                        # also leaves holes. Neither is proof of safe coverage.
                        # The current target contract cannot span such intervals.
                        raise RuntimeBlocked("delivery_contiguous_coverage_required")
                    key, value = message.key(), message.value()
                    headers = message.headers() or []
                    length = (len(key or b"") + len(value or b"")
                              + sum(len(k.encode()) + len(v or b"") for k, v in headers))
                    if length > self.limits.max_record_bytes:
                        raise RuntimeBlocked("delivery_record_capacity_exceeded")
                    records.append(self.decoder.decode(offset=message.offset(), key=key, value=value))
                    size += length
                self.consumer.pause([partition])
                if not records:
                    return 0
                # Recheck topic incarnation immediately before any row effects.
                self.identity.verify(b, self.limits.metadata_seconds)
                end = self._apply(records)
                if end != records[-1].offset:
                    raise RuntimeBlocked("delivery_coverage_invalid")
                result = self.consumer.commit(
                    offsets=[TopicPartition(b.topic, b.partition_identity.partition, end + 1)],
                    asynchronous=False,
                )
                if not result or any(item.error for item in result):
                    raise RuntimeBlocked("delivery_ack_unconfirmed")
                return len(records)
        except Exception:
            # Never carry records, driver exceptions, row values or a speculative
            # next offset into retries. The next call seeks target coverage.
            raise RuntimeBlocked("capture_delivery_blocked") from None
        finally:
            if assigned:
                try:
                    self.consumer.unassign()
                except Exception:
                    # No commits on close; restart still uses the target fence.
                    self.closed = True
                    try:
                        self.consumer.close()
                    except Exception:
                        pass

    def stop(self):
        self.stopping.set()

    def run(self):
        """Blocking independent runtime loop; call stop from the process signal handler."""
        try:
            while not self.stopping.is_set() and not self.closed:
                try:
                    if self.poll_once() == 0:
                        self.stopping.wait(self.limits.poll_seconds)
                except RuntimeBlocked:
                    if self.closed:
                        raise
                    self.stopping.wait(self.limits.retry_seconds)
        finally:
            self.close()

    def close(self):
        self.stop()
        if not self.closed:
            self.closed = True
            try:
                self.consumer.close()
            except Exception:
                raise RuntimeBlocked("capture_delivery_close_unconfirmed") from None


# Keep policy explicit: caller cannot override offset/assignment semantics,
# logging callbacks, interceptors, unbounded queues or plaintext transport.
CLIENT_KEYS = {"bootstrap.servers", "security.protocol", "ssl.ca.location",
               "ssl.certificate.location", "ssl.key.location", "ssl.key.password",
               "sasl.mechanism", "sasl.username", "sasl.password", "client.id"}


def open_delivery(*, kafka_config, group_id, applier_engine, binding, decoder,
                  admission, limits=DeliveryLimits()):
    """Create real clients and the sole SQL Application; does not start services.

    Invoke ``run()`` in a dedicated process, or ``poll_once()`` from the capture
    process reconciliation loop. Secrets must come from the existing protected
    secret installation, never from row/config logs. Target engine must be the
    bounded, validated refraq_mirror_applier engine from runtime composition.
    """
    consumer = None
    try:
        limits.validate()
        binding.validate(decoder)
        if (set(kafka_config) - CLIENT_KEYS or not callable(admission)
                or kafka_config.get("security.protocol") not in {"SSL", "SASL_SSL"}
                or not kafka_config.get("bootstrap.servers")
                or not kafka_config.get("ssl.ca.location")
                or not isinstance(group_id, str) or not group_id):
            raise RuntimeBlocked("delivery_client_profile_invalid")
        # librdkafka otherwise writes broker/config diagnostics to stderr,
        # including endpoints. Discard its raw diagnostics at the boundary.
        logger = logging.Logger("capture.kafka.discard", level=logging.CRITICAL + 1)
        logger.propagate = False
        logger.addHandler(logging.NullHandler())
        common = {**kafka_config, "enable.ssl.certificate.verification": True,
                  "ssl.endpoint.identification.algorithm": "https",
                  "socket.timeout.ms": int(limits.metadata_seconds * 1000),
                  "log_level": 0, "logger": logger}
        admin = AdminClient(common)
        consumer = Consumer({
            **common, "group.id": group_id, "enable.auto.commit": False,
            "enable.auto.offset.store": False, "auto.offset.reset": "error",
            "allow.auto.create.topics": False, "enable.partition.eof": False,
            "isolation.level": "read_committed",
            "queued.max.messages.kbytes": limits.queue_kbytes,
            "fetch.message.max.bytes": limits.max_record_bytes,
            "fetch.max.bytes": limits.max_batch_bytes,
            "receive.message.max.bytes": limits.max_batch_bytes + 1048576,
        })
        return KafkaDelivery(consumer=consumer, identity=KafkaIdentity(admin),
                             application=Application(applier_engine), binding=binding,
                             decoder=decoder, admission=admission, limits=limits)
    except Exception:
        if consumer is not None:
            try:
                consumer.close()
            except Exception:
                pass
        raise RuntimeBlocked("capture_delivery_configuration_invalid") from None
