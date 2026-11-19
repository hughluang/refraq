"""Immutable transport values for the Metadata-owned target adapter."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Authority:
    source_id: str
    resource_binding_id: str
    owner_epoch: int
    runtime_instance_id: str
    control_revision: int
    credential_revision: int
    capture_generation: str


@dataclass(frozen=True)
class PartitionIdentity:
    runtime_cluster_id: str
    topic_incarnation_id: str
    partition: int


@dataclass(frozen=True)
class AnchoredProfile:
    """Fixed Kafka log lineage enrolled at fresh disposable generation allocation."""

    leader_epoch: int
    kind: str = field(default="disposable_read_committed_v1", init=False)


@dataclass(frozen=True)
class ReadCommittedBounds:
    low: int
    stable: int
    high: int
    leader_epoch: int


@dataclass(frozen=True)
class AnchoredScan:
    """Evidence from a single ordered scan ending at a decoded visible record."""

    start: int
    end: int
    before: ReadCommittedBounds
    after: ReadCommittedBounds
    offsets: tuple[int, ...]


@dataclass(frozen=True)
class SealedScan(AnchoredScan):
    """A disposable scan ending at an explicit partition EOF under exclusion."""

    eof: int


@dataclass(frozen=True)
class Record:
    offset: int
    table_identity: str
    capture_generation: str
    operation: str
    origin: str
    key: dict[str, Any]
    values: dict[str, Any] | None
    unchanged_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Pin:
    run_id: str
    mirror_id: str
    generation_id: str
    source_id: str
