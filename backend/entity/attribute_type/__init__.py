"""Attribute Type closed set, config, physical column, operators, and codec.

Callers import from this package and ask ``resolve(name)`` for behavior.
"""

from backend.entity.attribute_type.operators import (
    OPERATOR_SPECS,
    OperatorArity,
    OperatorSpec,
    OperatorValueDomain,
    resolve_operator,
)
from backend.entity.attribute_type.types import ConfigChange, export_catalog, resolve

__all__ = [
    "ConfigChange",
    "OPERATOR_SPECS",
    "OperatorArity",
    "OperatorSpec",
    "OperatorValueDomain",
    "export_catalog",
    "resolve",
    "resolve_operator",
]
