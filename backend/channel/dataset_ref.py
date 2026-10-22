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

    Each column keeps ``name`` and ``type``. ``type`` is the Normalized Type
    stored as ``normalized_type`` on the registry row, not the physical
    PostgreSQL type.
    """
    return {
        "dataset_id": dataset_id,
        "columns": [
            {"name": column["name"], "type": column["normalized_type"]} for column in columns
        ],
        "count": count,
    }
