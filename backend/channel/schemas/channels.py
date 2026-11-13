"""HTTP shapes for Data Channel definitions, drafts, and versions."""

from __future__ import annotations

import keyword
import re
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from backend.core.pagination import OffsetPage
from backend.core.time import Instant

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RUN_TIMEOUT_MAX = 252_460_800


class PositionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


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
    parent: str | None = None
    execution_order: int | None = Field(default=None, ge=0, le=9_007_199_254_740_991, strict=True)

    @field_validator("execution_order", mode="before")
    @classmethod
    def _execution_order(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("execution_order must be a non-negative integer")
        return value

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

    @field_validator("parent")
    @classmethod
    def _parent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _ID_RE.fullmatch(value) is None:
            raise ValueError("parent is not a node id")
        return value

    @model_serializer(mode="wrap")
    def _omit_empty_parent(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if document.get("parent") is None:
            document.pop("parent", None)
        if document.get("execution_order") is None:
            document.pop("execution_order", None)
        return document


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
    keep_succeeded_runs: bool = True
    keep_failed_runs: bool = True
    keep_test_runs: bool = True

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


class SizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: float = Field(ge=160, le=2000)
    height: float = Field(ge=80, le=2000)


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_ID_RE.pattern)
    position: PositionIn
    size: SizeIn
    text: str = Field(max_length=4000)


class LayoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "manual"]


class GraphIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[NodeIn]
    edges: list[EdgeIn]
    notes: list[NoteIn] = Field(default_factory=list, max_length=200)
    settings: GraphSettingsIn
    layout: LayoutIn | None = None

    @model_validator(mode="before")
    @classmethod
    def _auto_positions(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if "layout" in value and value["layout"] is None:
            raise ValueError("layout must declare a mode")
        layout = value.get("layout")
        if isinstance(layout, dict) and layout.get("mode") == "auto":
            nodes = value.get("nodes")
            if isinstance(nodes, list):
                value = {**value, "nodes": [
                    {"position": {"x": 0, "y": 0}, **node}
                    if isinstance(node, dict) else node
                    for node in nodes
                ]}
        return value

    @model_validator(mode="after")
    def _auto_execution_order(self) -> GraphIn:
        if self.layout is not None and self.layout.mode == "auto":
            for index, node in enumerate(self.nodes):
                if node.execution_order is None:
                    node.execution_order = index
        return self

    @model_serializer(mode="wrap")
    def _omit_empty_notes(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if not document.get("notes"):
            document.pop("notes", None)
        if document.get("layout") is None:
            document.pop("layout", None)
        return document

    @model_validator(mode="after")
    def _unique_ids(self) -> GraphIn:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node id is duplicated")
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("edge id is duplicated")
        note_ids = [note.id for note in self.notes]
        if len(note_ids) != len(set(note_ids)):
            raise ValueError("note id is duplicated")
        if set(note_ids) & (set(node_ids) | set(edge_ids)):
            raise ValueError("note id is used by a node or an edge")
        refs = [node.ref for node in self.nodes]
        if len(refs) != len(set(refs)):
            raise ValueError("node ref is duplicated")
        return self


class ChannelTagAssignmentIn(BaseModel):
    """Tags submitted with Channel create. Omitted means an empty set."""

    model_config = ConfigDict(extra="forbid")

    tag_ids: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)


class ChannelCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    tags: ChannelTagAssignmentIn | None = None

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


class ChannelTagsReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision: int
    tag_ids: list[str]
    names: list[str]


class ChannelTagsReplaceResponse(BaseModel):
    tags: list[ChannelTagOut]
    tag_revision: int


class ChannelBulkTagsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_ids: list[str]
    tag_ids: list[str]


class ChannelBulkSubjectOut(BaseModel):
    id: str
    tags: list[ChannelTagOut]
    tag_revision: int


class ChannelBulkTagsResponse(BaseModel):
    subjects: list[ChannelBulkSubjectOut]


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


class ChannelTagOut(BaseModel):
    id: str
    name: str


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
    tags: list[ChannelTagOut]
    tag_revision: int
    created_at: Instant
    updated_at: Instant


class ChannelResponse(BaseModel):
    channel: ChannelOut


class ChannelListResponse(OffsetPage[ChannelOut]):
    pass


class SourceDisplayOut(BaseModel):
    """Presentation of one referenced Source. Omitted from the stored graph."""

    source_id: str
    key: str | None = None
    name: str | None = None
    inaccessible: bool = False

    @model_serializer(mode="wrap")
    def _present(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if document.get("inaccessible"):
            return {"source_id": document["source_id"], "inaccessible": True}
        presented = {"source_id": document["source_id"]}
        if document.get("key") is not None:
            presented["key"] = document["key"]
        if document.get("name") is not None:
            presented["name"] = document["name"]
        return presented


class DraftResponse(BaseModel):
    """Stored draft. ``graph`` is the stored document, not re-checked as ``GraphIn``."""

    draft_revision: int
    draft_updated_at: Instant
    graph: dict[str, Any]
    source_displays: list[SourceDisplayOut] = Field(default_factory=list)


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
    source_displays: list[SourceDisplayOut] = Field(default_factory=list)


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


class OutputViewOut(BaseModel):
    kind: Literal["record", "rows", "dataset", "counts", "container", "value"]
    metrics: list[str]
    rows: str | None = None
    dataset: str | None = None
    item: str | None = None

    @model_serializer(mode="wrap")
    def _omit_empty_keys(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        document = handler(self)
        if document.get("rows") is None:
            document.pop("rows", None)
        if document.get("dataset") is None:
            document.pop("dataset", None)
        if document.get("item") is None:
            document.pop("item", None)
        return document


class ContainerOut(BaseModel):
    round_templates: list[str]


class NodeTypeOut(BaseModel):
    type: str
    family: str
    label: str
    summary: str
    description: str
    trigger: bool
    container: ContainerOut | None
    inputs: list[PortOut]
    outputs: list[PortOut]
    output_view: OutputViewOut
    config_schema: dict[str, Any]
    permission: str | None
    type_version: int


class NodeTypeListResponse(BaseModel):
    items: list[NodeTypeOut]


class DatasetCapacityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used_bytes: int
    ceiling_bytes: int


class ChannelDatasetListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    job_id: str
    channel_id: str | None
    channel_name: str
    node_id: str
    node_name: str
    status: Literal["loading", "ready"]
    size_bytes: int
    row_count: int
    created_at: Instant
    expires_at: Instant | None


class ChannelDatasetListResponse(OffsetPage[ChannelDatasetListItem]):
    """Offset Page of loading and ready channel datasets."""
