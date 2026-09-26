"""Closed object_category set for Catalog Object Semantics."""

from __future__ import annotations

from typing import Literal

ObjectCategory = Literal[
    "transaction_fact",
    "master_data",
    "dimension",
    "reference",
    "event",
]

__all__ = ["ObjectCategory"]
