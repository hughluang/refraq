"""Bounded fleet summaries and searchable Operations projections."""

from typing import Literal

from backend.core.time import Instant
from backend.metadata.mirrors.diagnostic_schemas import Health, Link
from backend.metadata.mirrors.schemas import Mirror, StrictModel

GroupedState = Literal["synchronizing", "copying", "attention", "stopped"]
AttentionCause = Literal["schema", "permission", "continuity", "pending_stop", "source_prerequisite", "snapshot_evidence"]
InventorySort = Literal["priority", "size", "rows", "table"]


class ObservedTotal(StrictModel):
    value: int | None
    sampled: int
    missing: int


class StateCount(StrictModel):
    count: int
    percent: float | None


class SnapshotTotal(StrictModel):
    scanned_bytes: int | None
    source_size_bytes: int | None
    sampled: int
    missing: int
    queued: int


class SourceFleet(StrictModel):
    id: str
    name: str
    runtime_instance_id: str | None
    health: Health
    segment_health: dict[Link, Health]
    mirror_count: int
    attention_count: int
    source_size: ObservedTotal
    estimated_rows: ObservedTotal


class FleetOverview(StrictModel):
    observed_at: Instant
    mirror_count: int
    source_count: int
    source_size: ObservedTotal
    estimated_rows: ObservedTotal
    published_count: int
    published_percent: float | None
    attention_count: int
    states: dict[GroupedState, StateCount]
    snapshot: SnapshotTotal
    health: dict[Health, int]
    segments: dict[Link, dict[Health, int]]
    ranking: list[SourceFleet]
    ranking_total: int


class SourceFleetPage(StrictModel):
    items: list[SourceFleet]
    total: int
    limit: int
    offset: int


class RuntimeFleet(StrictModel):
    id: str
    runtime_instance_id: str | None
    source_count: int
    affected_source_count: int
    health: Health


class RuntimeFleetPage(StrictModel):
    items: list[RuntimeFleet]
    total: int
    limit: int
    offset: int


class InventoryItem(Mirror):
    grouped_state: GroupedState
    attention_cause: AttentionCause | None
    attention_since: Instant | None
    source_size_bytes: int | None
    estimated_rows: int | None


class InventoryPage(StrictModel):
    items: list[InventoryItem]
    total: int
    limit: int
    offset: int
    cause_counts: dict[AttentionCause, int]
