"""Catalog HTTP/MCP object and column presentation.

One projection; adapters pick a surface profile. MCP omits ``normalized_type``
(ADR 0024) and omits foreign keys / indexes on object payloads. HTTP list
summaries keep empty nested arrays per the HTTP contract.
"""

from __future__ import annotations

from dataclasses import asdict
from enum import Enum
from typing import Any

from backend.metadata.catalog.views import ColumnView, ObjectView


class ObjectPresentProfile(str, Enum):
    HTTP_SUMMARY = "http_summary"
    HTTP_DETAIL = "http_detail"
    MCP_SUMMARY = "mcp_summary"
    MCP_DETAIL = "mcp_detail"
    MCP_COLUMNS = "mcp_columns"
    MCP_DDL = "mcp_ddl"


def present_column(view: ColumnView, *, include_normalized_type: bool) -> dict[str, Any]:
    payload = asdict(view)
    if not include_normalized_type:
        payload.pop("normalized_type", None)
    return payload


def present_object(view: ObjectView, *, profile: ObjectPresentProfile) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": view.id,
        "locator_key": view.locator_key,
        "source_id": view.source_id,
        "object_type": view.object_type,
        "schema_name": view.schema_name,
        "name": view.name,
        "comment": view.comment,
        "primary_key": view.primary_key,
        "business_name": view.business_name,
        "business_description": view.business_description,
        "object_category": view.object_category,
        "grain_description": view.grain_description,
        "business_primary_key": view.business_primary_key,
        "business_domain": asdict(view.business_domain) if view.business_domain else None,
        "evidence_summary": view.evidence_summary,
        "open_questions": view.open_questions,
        "semantic_source": view.semantic_source,
        "business_semantics_ready": view.business_semantics_ready,
        "semantics_updated_at": view.semantics_updated_at,
        "is_present": view.is_present,
        "collected_at": view.collected_at,
    }
    if profile is ObjectPresentProfile.MCP_SUMMARY:
        return payload
    if profile is ObjectPresentProfile.MCP_DDL:
        return {
            "locator_key": view.locator_key,
            "ddl": view.ddl,
            "has_definition": bool(view.ddl),
        }
    if profile is ObjectPresentProfile.MCP_COLUMNS:
        payload["columns"] = [
            present_column(c, include_normalized_type=False) for c in view.columns
        ]
        return payload
    if profile is ObjectPresentProfile.HTTP_SUMMARY:
        payload["columns"] = []
        payload["foreign_keys"] = []
        payload["indexes"] = []
        payload["ddl"] = None
        return payload
    if profile is ObjectPresentProfile.MCP_DETAIL:
        payload["ddl"] = view.ddl
        payload["columns"] = [
            present_column(c, include_normalized_type=False) for c in view.columns
        ]
        return payload
    payload["columns"] = [
        present_column(c, include_normalized_type=True) for c in view.columns
    ]
    payload["foreign_keys"] = [asdict(fk) for fk in view.foreign_keys]
    payload["indexes"] = [asdict(idx) for idx in view.indexes]
    payload["ddl"] = view.ddl
    return payload
