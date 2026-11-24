"""Allowlisted operational observations, never connector responses or row values."""

from typing import Literal

from pydantic import Field, model_validator

from backend.core.time import Instant
from backend.metadata.mirrors.schemas import StrictModel

Link = Literal["replication", "production", "consumption", "storage"]
Health = Literal["healthy", "failed", "stale", "unobserved"]


class TimedObservation(StrictModel):
    observed_at: Instant
    valid_until: Instant

    @model_validator(mode="after")
    def valid_window(self):
        if self.valid_until <= self.observed_at:
            raise ValueError("Observation validity must be positive")
        return self


class LinkObservation(TimedObservation):
    outcome: Literal["healthy", "failed"]
    error_code: Literal["REPLICATION_UNAVAILABLE", "PRODUCTION_UNAVAILABLE", "CONSUMPTION_UNAVAILABLE", "STORAGE_UNAVAILABLE"] | None = None

    @model_validator(mode="after")
    def failure_code(self):
        if (self.outcome == "failed") != (self.error_code is not None):
            raise ValueError("Only failures carry an allowlisted error code")
        return self


class MirrorSample(TimedObservation):
    mirror_id: str = Field(min_length=1, max_length=64)
    capture_generation: str = Field(min_length=1, max_length=128)
    generation_id: str = Field(min_length=1, max_length=64)
    interval_start: Instant
    interval_end: Instant
    captured_events: int | None = Field(default=None, strict=True, ge=0)
    committed_events: int | None = Field(default=None, strict=True, ge=0)
    committed_batches: int | None = Field(default=None, strict=True, ge=0)
    captured_bytes: int | None = Field(default=None, strict=True, ge=0)
    committed_bytes: int | None = Field(default=None, strict=True, ge=0)
    pending_events: int | None = Field(default=None, strict=True, ge=0)
    pending_bytes: int | None = Field(default=None, strict=True, ge=0)
    position_lag: int | None = Field(default=None, strict=True, ge=0)
    capture_state: Literal["active", "idle", "blocked", "unobserved"] = "unobserved"
    write_state: Literal["active", "idle", "blocked", "unobserved"] = "unobserved"
    last_target_commit_at: Instant | None = None
    freshness_ms: int | None = Field(default=None, strict=True, ge=0)
    checkpoint_ref: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def interval_and_proof(self):
        if not self.interval_start < self.interval_end <= self.observed_at:
            raise ValueError("A sample must cover a positive completed interval")
        if self.freshness_ms is not None and self.checkpoint_ref is None:
            raise ValueError("Freshness requires verified end-to-end checkpoint evidence")
        return self


class RowSample(TimedObservation):
    generation_id: str = Field(min_length=1, max_length=64)
    row_count: int = Field(strict=True, ge=0)


class SourceReceipt(StrictModel):
    checks: dict[Link, LinkObservation] = Field(default_factory=dict, max_length=4)
    samples: list[MirrorSample] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_scope(self):
        if len({sample.mirror_id for sample in self.samples}) != len(self.samples):
            raise ValueError("Only one interval per Mirror is accepted in a round")
        if any(check.error_code and check.error_code != f"{link.upper()}_UNAVAILABLE"
               for link, check in self.checks.items()):
            raise ValueError("Failure code does not match the checked link")
        return self


class DiagnosticPolicy(StrictModel):
    heartbeat_interval_seconds: int = Field(strict=True, gt=0, le=3600)
    heartbeat_valid_seconds: int = Field(strict=True, gt=0, le=86400)
    check_valid_seconds: int = Field(strict=True, gt=0, le=86400)
    sample_valid_seconds: int = Field(strict=True, gt=0, le=86400)
    round_valid_seconds: int = Field(strict=True, gt=0, le=86400)
    row_count_interval_seconds: int = Field(strict=True, gt=0, le=86400)
    row_count_timeout_ms: int = Field(strict=True, gt=0, le=60000)
    row_count_lock_timeout_ms: int = Field(strict=True, gt=0, le=60000)

    @model_validator(mode="after")
    def bounded_work(self):
        if self.heartbeat_interval_seconds >= self.heartbeat_valid_seconds:
            raise ValueError("Heartbeat validity must exceed its interval")
        if self.row_count_lock_timeout_ms >= self.row_count_timeout_ms:
            raise ValueError("Lock timeout must be shorter than the count timeout")
        return self


class CheckView(StrictModel):
    link: Link
    health: Health
    observed_at: Instant | None
    valid_until: Instant | None
    last_success_at: Instant | None
    failure_at: Instant | None
    error_code: str | None


class RoundView(StrictModel):
    id: str
    at: Instant
    health: Health
    checks: list[CheckView]


class SourceView(StrictModel):
    id: str
    name: str
    runtime_instance_id: str | None
    health: Health
    checks: list[CheckView]
    history: list[RoundView | None]
    last_checked_at: Instant | None
    end_of_cycle_wait_seconds: float | None


class SampleView(MirrorSample):
    stale: bool


class MeasurementResponse(StrictModel):
    mirror_id: str
    source_id: str
    sample: SampleView | None
    row_sample: RowSample | None
    row_sample_stale: bool
    estimated_rows: int | None
    published_generation_id: str | None
    runtime_instance_id: str | None
    last_source_check_at: Instant | None
    end_of_cycle_wait_seconds: float | None


class MetricView(StrictModel):
    value: int | None
    sampled: int
    missing: int
    interval_start: Instant | None
    interval_end: Instant | None
    oldest_observation: Instant | None
    newest_observation: Instant | None


class CycleView(TimedObservation):
    started_at: Instant
    completed_at: Instant | None
    duration_seconds: float | None
    last_completed_at: Instant | None
    last_duration_seconds: float | None


class RuntimeView(StrictModel):
    id: str
    heartbeat: TimedObservation | None
    heartbeat_health: Health
    cycle: CycleView | None
    cycle_health: Health
    end_of_cycle_wait_seconds: float | None
    assignment_stale: bool
    source_ids: list[str]
    assignment_offset: int
    total_sources: int


class IntervalView(StrictModel):
    mirror_id: str
    qualified_table: str
    interval_start: Instant | None
    interval_end: Instant | None
    observed_at: Instant | None
    stale: bool


class DiagnosticsResponse(StrictModel):
    observed_at: Instant
    mirror_count: int
    source_count: int
    sources: list[SourceView]
    matching_sources: int
    source_offset: int
    runtimes: list[RuntimeView]
    runtime_offset: int
    assignment_offset: int
    total_runtimes: int
    summary: dict[Literal['captured_events', 'committed_events', 'committed_batches', 'pending_events', 'pending_bytes', 'position_lag'], MetricView]
    states: dict[Literal['capture', 'write'], dict[Literal['active', 'idle', 'blocked', 'unobserved'], int]]
    intervals: list[IntervalView]
    link_counts: dict[Health, int]
