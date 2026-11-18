"""Strict public mirror management shapes; never row-bearing target payloads."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.time import Instant

MirrorStatus = Literal["waiting", "snapshotting", "catching_up", "ready", "stale", "rebuilding", "paused", "needs_attention", "disable_pending", "unknown", "disabled", "source_fault"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Control(StrictModel):
    control_revision: int
    credential_revision: int | None
    owner_epoch: int | None
    runtime_instance_id: str | None
    applied_revision: int | None
    observed_at: Instant | None
    stop_ack: None = None


class Readiness(StrictModel):
    key: str
    result: Literal["pass", "fail", "unknown", "not_applicable"]
    expected: str | None
    observed: str | None
    observed_at: Instant | None
    owner: str
    action: str


class Operation(StrictModel):
    id: str
    mirror_id: str
    kind: Literal["open", "enable", "disable", "recovery"]
    state: Literal["pending", "applied", "superseded"]
    control_revision: int
    observed_evidence_refs: list[str]
    fault_code: str | None
    requested_at: Instant


class Profile(StrictModel):
    qualification: Literal["unverified", "qualified"]


class Mirror(StrictModel):
    id: str
    source_id: str
    object_id: str
    source_key: str
    source_name: str
    table_identity: str
    qualified_table: str
    enabled: bool
    status: MirrorStatus
    published_generation_id: str | None
    capture_generation: str | None
    history_epoch: str | None
    retained_lower_bound: None = None
    committed_upper_bound: None = None
    control: Control
    progress: None = None
    profile: Profile
    readiness: list[Readiness]
    fault: None = None
    published_reference_count: int
    operations: list[Operation]


class MirrorResponse(StrictModel):
    mirror: Mirror


class MirrorListResponse(StrictModel):
    items: list[Mirror]
    total: int
    limit: int
    offset: int


class PatchMirrorRequest(StrictModel):
    enabled: bool = Field(strict=True)


class PatchMirrorResponse(MirrorResponse):
    operation_id: str


class RecoveryResponse(StrictModel):
    operation_id: str
    state: Literal["pending"]
