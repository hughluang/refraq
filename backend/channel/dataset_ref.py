"""Dataset reference value. The physical relation is not part of the value."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ["DATASET_REFERENCE_SCHEMA", "dataset_reference"]

DATASET_REFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "x-refraq-dataset-reference": True,
    "required": ["dataset_id", "columns", "count"],
    "properties": {
        "dataset_id": {"type": "string"},
        "columns": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "type"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                    "temporal_kind": {
                        "type": ["string", "null"],
                        "enum": [
                            "date",
                            "time",
                            "time_with_offset",
                            "local_datetime",
                            "timestamp_with_time_zone",
                            "timestamp_with_local_time_zone",
                            "interval",
                            "interval_calendar",
                            "interval_fixed",
                            None,
                        ],
                    },
                    "precision": {"type": ["integer", "null"], "minimum": 0},
                    "nullable": {"type": ["boolean", "null"]},
                },
            },
        },
        "count": {"type": "integer", "minimum": 0},
    },
}


def dataset_reference(
    *,
    dataset_id: str,
    columns: Sequence[Mapping[str, Any]],
    count: int,
) -> dict[str, Any]:
    """``{dataset_id, columns, count}``.

    Each column keeps ``name`` and ``type``, plus the temporal declaration.
    ``type`` is the Normalized Type stored as ``normalized_type`` on the
    registry row, not the physical PostgreSQL type. ``precision`` is the
    fractional precision already declared for a temporal column.
    """
    return {
        "dataset_id": dataset_id,
        "columns": [_reference_column(column) for column in columns],
        "count": count,
    }


def _reference_column(column: Mapping[str, Any]) -> dict[str, Any]:
    kind = column.get("temporal_kind")
    precision = column.get("precision") if kind else None
    return {
        "name": column["name"],
        "type": column["normalized_type"],
        "temporal_kind": kind,
        "precision": precision,
        "nullable": column.get("nullable"),
    }
