"""Strict public mirror management shapes; never row-bearing target payloads."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.core.time import Instant

MirrorStatus = Literal["waiting", "snapshotting", "catching_up", "ready", "stale", "rebuilding", "paused", "needs_attention", "disable_pending", "unknown", "disabled", "source_fault"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StopAcknowledgment(StrictModel):
    operation_id: str
    source_operation_id: str
    observed_at: Instant


class Control(StrictModel):
    control_revision: int
    credential_revision: int | None
    owner_epoch: int | None
    runtime_instance_id: str | None
    applied_revision: int | None
    observed_at: Instant | None
    stop_ack: StopAcknowledgment | None = None


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
    kind: Literal["open", "enable", "disable", "delete", "recovery", "retry"]
    state: Literal["pending", "applied", "superseded"]
    control_revision: int
    observed_evidence_refs: list[str]
    fault_code: str | None
    requested_at: Instant


class Profile(StrictModel):
    qualification: Literal["unverified", "qualified"]


class HistoryPosition(StrictModel):
    mirror_id: str
    history_epoch: str
    commit_seq: int = Field(strict=True, ge=0)
    entry_seq: int = Field(strict=True, ge=0)


class SnapshotProgress(StrictModel):
    stage: Literal["scan", "catching_up"]
    notification_offset: int = Field(ge=0)
    generation_id: str
    observed_at: Instant | None
    scanned_bytes: int | None = Field(default=None, ge=0)
    byte_notification_offset: int | None = Field(default=None, ge=0)
    bytes_observed_at: Instant | None = None
    scan_percent: float | None = Field(default=None, ge=0, le=100)
    scan_complete: bool = False


class SnapshotSlotHolder(StrictModel):
    mirror_id: str
    qualified_table: str


class Mirror(StrictModel):
    id: str
    source_id: str
    object_id: str
    source_key: str
    source_name: str
    source_engine: str
    table_identity: str
    qualified_table: str
    enabled: bool
    deletion_operation_id: str | None = None
    status: MirrorStatus
    published_generation_id: str | None
    capture_generation: str | None
    history_epoch: str | None
    retained_lower_bound: HistoryPosition | None = None
    committed_upper_bound: HistoryPosition | None = None
    control: Control
    progress: SnapshotProgress | None = None
    snapshot_slot_holder: SnapshotSlotHolder | None = None
    publication_wait: SnapshotSlotHolder | None = None
    profile: Profile
    readiness: list[Readiness]
    fault: None = None
    operations: list[Operation]


class MirrorResponse(StrictModel):
    mirror: Mirror


class JournalEvent(StrictModel):
    id: str
    category: Literal["request", "observation"]
    kind: str
    at: Instant
    operation_id: str
    control_revision: int
    history_epoch: str | int | None
    generation_id: str | None
    outcome: str | None
    outcome_at: Instant | None
    related_operation_id: str | None


class JournalPage(StrictModel):
    items: list[JournalEvent]
    next_cursor: str | None


class MirrorBlocker(StrictModel):
    cause: Literal["continuity", "permission", "schema"]
    since: Instant
    last_checked_at: Instant


class MirrorDetail(Mirror):
    journal: JournalPage
    open_request: JournalEvent | None
    latest_request: JournalEvent | None
    latest_observation: JournalEvent | None
    continuity_check: JournalEvent | None
    can_retry: bool
    blocker: MirrorBlocker | None
    published_at: Instant | None
    allocated_generation_id: str | None
    source_size_bytes: int | None = Field(ge=0)
    estimated_rows: int | None = Field(ge=0)
    storage_destination: str


class MirrorDetailResponse(MirrorResponse):
    mirror: MirrorDetail
    can_enable: bool


class PatchMirrorRequest(StrictModel):
    enabled: bool = Field(strict=True)


class PatchMirrorResponse(MirrorResponse):
    operation_id: str


class MirrorActionReceipt(StrictModel):
    operation_id: str
    enabled: bool


class RecoveryResponse(StrictModel):
    operation_id: str
    state: Literal["pending"]


class SetupInput(StrictModel):
    token: str
    kind: Literal["https_origin", "bootstrap_servers", "identifier", "connector_name", "topic_prefix", "directory"]


class SetupBounds(StrictModel):
    poll_interval_seconds_max: int
    sources_max: int
    timeout_seconds_max: int
    max_response_bytes_max: int
    readiness_max_age_seconds: int


class SetupPatterns(StrictModel):
    connector_name: str
    topic_prefix: str
    bootstrap_servers: str


class SetupTarget(StrictModel):
    schema_version: int
    schemas: list[str]
    roles: list[str]
    login_roles: list[str]
    setting: str
    setting_fields: list[str]
    driver: str
    sslmode: str
    url_template: str
    bootstrap_env: str


class SetupCommand(StrictModel):
    argv: list[str]
    env: list[str]
    mount: str | None
    host: bool


class SetupExitCodes(StrictModel):
    ready: int
    blocked: int


class SetupRuntime(StrictModel):
    config_keys: list[str]
    check_flag: str
    recovery_flag: str
    exit_codes: SetupExitCodes
    fatal_message: str
    fault_codes: list[str]
    readiness_policy_keys: list[str]
    credential_file_keys: list[str]
    delivery_settings_keys: list[str]
    native_types: list[str]


class SetupGateway(StrictModel):
    paths: list[str]
    optional_paths: list[str]
    connect_paths: list[str]
    required_checks: list[str]
    signing_trust_keys: list[str]
    snapshot_observer_keys: list[str]


class SetupTransport(StrictModel):
    tls_keys: list[str]
    data_partition: int


class SetupEngine(StrictModel):
    code: str
    profile_key: str
    prerequisites: list[str]
    snapshot_prerequisite: str
    source_entry: dict[str, Any]


class MirrorSetupGuide(StrictModel):
    connector_version: str
    compose_service: str
    site_inputs: list[SetupInput]
    steps: list[str]
    bounds: SetupBounds
    patterns: SetupPatterns
    protected_forbidden_bits: int
    target: SetupTarget
    commands: dict[str, SetupCommand]
    runtime_config: dict[str, Any]
    runtime: SetupRuntime
    gateway: SetupGateway
    transport: SetupTransport
    deployment_owned: list[str]
    engines: list[SetupEngine]
