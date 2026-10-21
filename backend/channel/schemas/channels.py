"""HTTP shapes for Data Channel definitions, drafts, and versions."""

from __future__ import annotations

import keyword
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.core.pagination import OffsetPage
from backend.core.time import Instant

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RUN_TIMEOUT_MAX = 252_460_800


class PositionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class RetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tries: int = Field(ge=1, le=10)
    wait_sec: int = Field(ge=0, le=3600)


_RESERVED_REFS = frozenset({"nodes", "channel", "run", "platform"})


class NodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_ID_RE.pattern)
    ref: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=64)
    name: str
    position: PositionIn
    config: dict[str, Any]
    on_error: Literal["stop", "continue", "error_output"] = "stop"
    retry: RetryIn | None = None
    type_version: int = Field(default=1, ge=1)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 128:
            raise ValueError("name must be 1 to 128 characters")
        return cleaned

    @field_validator("ref")
    @classmethod
    def _ref(cls, value: str) -> str:
        if (
            not value.isidentifier()
            or keyword.iskeyword(value)
            or value.startswith("_")
            or value in _RESERVED_REFS
        ):
            raise ValueError("ref is not a usable Python identifier")
        return value


class PortRefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(pattern=_ID_RE.pattern)
    port: str = Field(min_length=1, max_length=64)


class EdgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_ID_RE.pattern)
    source: PortRefIn
    target: PortRefIn


class GraphSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_timeout_sec: int | None = None
    run_retry_limit: int | None = None
    error_channel_id: str | None = None

    @field_validator("run_timeout_sec")
    @classmethod
    def _timeout(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 1 or value > _RUN_TIMEOUT_MAX:
            raise ValueError("run_timeout_sec is out of range")
        return value

    @field_validator("run_retry_limit")
    @classmethod
    def _retry_limit(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if value < 0 or value > 10:
            raise ValueError("run_retry_limit is out of range")
        return value

    @field_validator("error_channel_id")
    @classmethod
    def _error_channel(cls, value: str | None) -> str | None:
        if value is not None and _ID_RE.fullmatch(value) is None:
            raise ValueError("error_channel_id is malformed")
        return value


class GraphIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[NodeIn]
    edges: list[EdgeIn]
    settings: GraphSettingsIn

    @model_validator(mode="after")
    def _unique_ids(self) -> GraphIn:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node id is duplicated")
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("edge id is duplicated")
        refs = [node.ref for node in self.nodes]
        if len(refs) != len(set(refs)):
            raise ValueError("node ref is duplicated")
        return self


class ChannelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 200:
            raise ValueError("name must be 1 to 200 characters")
        return cleaned

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 2000:
            raise ValueError("description must be at most 2000 characters")
        return value


class ChannelPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("name must be 1 to 200 characters")
        cleaned = value.strip()
        if not cleaned or len(cleaned) > 200:
            raise ValueError("name must be 1 to 200 characters")
        return cleaned

    @field_validator("description")
    @classmethod
    def _description(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 2000:
            raise ValueError("description must be at most 2000 characters")
        return value


class DraftPutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: int = Field(ge=1)
    graph: GraphIn


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_revision: int = Field(ge=1)


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph: GraphIn


class LatestVersionOut(BaseModel):
    number: int
    published_at: Instant


class ChannelOut(BaseModel):
    id: str
    name: str
    description: str | None
    active: bool
    draft_revision: int
    draft_updated_at: Instant
    latest_version: LatestVersionOut | None
    failure_streak: int
    persistently_failing: bool
    created_at: Instant
    updated_at: Instant


class ChannelResponse(BaseModel):
    channel: ChannelOut


class ChannelListResponse(OffsetPage[ChannelOut]):
    pass


class DraftResponse(BaseModel):
    """Stored draft. ``graph`` is the stored document, not re-checked as ``GraphIn``."""

    draft_revision: int
    draft_updated_at: Instant
    graph: dict[str, Any]


class ProblemOut(BaseModel):
    code: str
    node_id: str | None
    edge_id: str | None
    path: list[str | int] = Field(default_factory=list)
    detail: str
    severity: Literal["error", "warning"] = "error"


class RefinedPortOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    node_id: str
    port: str
    direction: Literal["input", "output"]
    coarse_type: str
    value_schema: dict[str, Any] | None = Field(alias="schema")


class ValidateResponse(BaseModel):
    valid: bool
    problems: list[ProblemOut]
    ports: list[RefinedPortOut]
    context: dict[str, Any]


class RunToCancelOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str
    version: int | None = None
    started_at: Instant | None = None


class ConfirmationOut(BaseModel):
    draft_revision: int
    mirrors_to_open: list[dict[str, Any]]
    runs_to_cancel: list[RunToCancelOut]
    missing_run_timeout: bool


class VersionSummaryOut(BaseModel):
    channel_id: str
    number: int
    published_at: Instant
    published_by_user_id: str
    published_by_name: str | None


class VersionOut(VersionSummaryOut):
    """Stored version. ``graph`` is the stored document, not re-checked as ``GraphIn``."""

    graph: dict[str, Any]


class VersionResponse(BaseModel):
    version: VersionOut


class VersionListResponse(OffsetPage[VersionSummaryOut]):
    pass


class PublishResponse(BaseModel):
    version: VersionOut
    confirmation: ConfirmationOut


class PortOut(BaseModel):
    port: str
    description: str
    coarse_type: str
    loop_back: bool = False


class NodeTypeOut(BaseModel):
    type: str
    family: str
    label: str
    summary: str
    description: str
    trigger: bool
    inputs: list[PortOut]
    outputs: list[PortOut]
    config_schema: dict[str, Any]
    permission: str | None
    type_version: int


class NodeTypeListResponse(BaseModel):
    items: list[NodeTypeOut]
