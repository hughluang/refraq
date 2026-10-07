"""HTTP request and response shapes for Business Entity."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from backend.core.pagination import OffsetPage
from backend.core.time import Instant
from backend.entity.attribute_type import resolve
from backend.entity.errors import EntityAttributeInvalid
from backend.jobs.schemas.jobs import JobOut

_RETIRED_ATTRIBUTE_FIELDS = (
    "kind",
    "normalized_type",
    "precision",
    "scale",
    "target_table_name",
    "enumeration",
    "inverse_attribute",
    "entries",
)


class AttributeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=63)
    type: str | None = None
    required: bool = False
    unique: bool = False
    indexed: bool = False
    business_key: bool = False
    description: str | None = None
    config: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_retired_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for key in _RETIRED_ATTRIBUTE_FIELDS:
            if key in data:
                raise EntityAttributeInvalid(
                    f"Attribute field '{key}' is not accepted"
                )
        attribute_type = data.get("type")
        if attribute_type in ("many2one", "one2many"):
            raise EntityAttributeInvalid(
                f"Attribute type '{attribute_type}' is not accepted"
            )
        return data

    @model_validator(mode="after")
    def _require_type_and_config(self) -> AttributeIn:
        spec = resolve(self.type or "")
        if not isinstance(self.config, dict):
            raise EntityAttributeInvalid(
                f"Attribute '{self.name}' requires config"
            )
        unknown = set(self.config) - spec.config_keys
        if unknown:
            listed = ", ".join(sorted(unknown))
            raise EntityAttributeInvalid(
                f"Attribute '{self.name}' of type {self.type} rejects config {listed}"
            )
        return self


class ReferenceTargetOut(BaseModel):
    entity_id: str
    name: str
    table_name: str
    business_key: str | None = None


class ReferenceSnapshotOut(BaseModel):
    attribute: str
    type: str
    max_length: int | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_length(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if data.get("max_length") is None:
            data.pop("max_length", None)
        return data


class DictionaryRefOut(BaseModel):
    id: str
    name: str
    display_name: str
    deprecated: bool


class AttributeOut(BaseModel):
    attribute_id: str | None = None
    name: str
    type: str
    required: bool
    unique: bool = False
    indexed: bool = False
    business_key: bool = False
    description: str | None = None
    config: dict[str, Any]
    target: ReferenceTargetOut | None = None
    reference_snapshot: ReferenceSnapshotOut | None = None
    dictionary: DictionaryRefOut | None = None
    behind: bool | None = None

    @model_serializer(mode="wrap")
    def _omit_type_specific(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        reads = resolve(str(data.get("type") or "")).reads
        if "target" not in reads:
            data.pop("target", None)
            data.pop("reference_snapshot", None)
        if "dictionary" not in reads:
            data.pop("dictionary", None)
            data.pop("behind", None)
        return data


class InboundReferenceOut(BaseModel):
    entity_id: str
    table_name: str
    attribute_name: str


class AlignmentOut(BaseModel):
    table_present: bool
    latest_job_id: str | None = None
    latest_job_status: str | None = None


class CurrentVersionOut(BaseModel):
    id: str
    version: int
    publish_status: str
    table_name: str | None
    alignment: AlignmentOut


class BusinessEntityOut(BaseModel):
    id: str
    table_name: str
    name: str
    description: str
    deprecated_at: Instant | None = None
    ever_published: bool = False
    current_version: CurrentVersionOut | None = None
    inbound_references: list[InboundReferenceOut] | None = None
    created_at: Instant
    updated_at: Instant

    @model_serializer(mode="wrap")
    def _omit_absent_inbound(
        self, handler: Any
    ) -> dict[str, Any]:
        data = handler(self)
        if data.get("inbound_references") is None:
            data.pop("inbound_references", None)
        return data


class EntityVersionOut(BaseModel):
    id: str
    entity_id: str
    version: int
    publish_status: str
    attributes: list[AttributeOut] | None = None
    attribute_count: int | None = None
    table_name: str | None
    alignment: AlignmentOut
    created_at: Instant
    updated_at: Instant


class ShapeChangeOut(BaseModel):
    field: str
    old_value: Any = None
    new_value: Any = None
    change_class: str = Field(alias="class")

    model_config = ConfigDict(populate_by_name=True)


class ClassificationOut(BaseModel):
    change_class: str = Field(alias="class")
    changes: list[ShapeChangeOut]

    model_config = ConfigDict(populate_by_name=True)


class BusinessEntityListResponse(OffsetPage[BusinessEntityOut]):
    pass


class BusinessEntityResponse(BaseModel):
    entity: BusinessEntityOut


class EntityVersionListResponse(OffsetPage[EntityVersionOut]):
    pass


class EntityVersionResponse(BaseModel):
    version: EntityVersionOut


class EntityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_name: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1)
    attributes: list[AttributeIn]


class EntityPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, min_length=1)
    attributes: list[AttributeIn] | None = None


class ShapeWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attributes: list[AttributeIn] | None = None


class EntityJobEnqueueResponse(BaseModel):
    job: JobOut | None = None
    version: EntityVersionOut | None = None
