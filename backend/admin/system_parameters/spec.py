"""Generic System Parameter declaration shape. No domain key names."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ParameterSource = Literal["seed", "user"]
ParameterValue = int | float | str | bool | None

JSON_SCHEMA_PROFILE_KEYWORDS = frozenset(
    {"type", "minimum", "maximum", "enum", "pattern", "maxLength"}
)


class ParameterConstraint(Protocol):
    def admit(self, value: object) -> bool: ...

    def fallback(self, value: object, seed: ParameterValue) -> ParameterValue: ...

    def to_json_schema(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class IntConstraint:
    """Closed integer constraint. Bounds are optional; omit a bound that is not a cliff."""

    minimum: int | None = None
    maximum: int | None = None
    optional: bool = False

    def admit(self, value: object) -> bool:
        if value is None:
            return self.optional
        if isinstance(value, bool) or not isinstance(value, int):
            return False
        if self.minimum is not None and value < self.minimum:
            return False
        if self.maximum is not None and value > self.maximum:
            return False
        return True

    def fallback(self, value: object, seed: ParameterValue) -> ParameterValue:
        if value is None:
            return None if self.optional else seed
        if isinstance(value, bool) or not isinstance(value, int):
            return seed
        if self.minimum is not None and value < self.minimum:
            return self.minimum
        if self.maximum is not None and value > self.maximum:
            return self.maximum
        return value

    def to_json_schema(self) -> dict[str, object]:
        fragment: dict[str, object] = {
            "type": ["integer", "null"] if self.optional else "integer",
        }
        if self.minimum is not None:
            fragment["minimum"] = self.minimum
        if self.maximum is not None:
            fragment["maximum"] = self.maximum
        return fragment


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    key: str
    constraint: IntConstraint
    seed: ParameterValue
    owner: str
    group: str
    operator_action_required: bool
    apply_note_key: str
    label_key: str
    help_key: str
