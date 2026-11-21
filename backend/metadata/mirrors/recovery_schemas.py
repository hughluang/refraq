"""Recovery accepts opaque epochs emitted by the authoritative history gate."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.metadata.mirrors.schemas import StrictModel


class RecoveryRequest(StrictModel):
    action: Literal["retry", "run_now", "postpone", "manual"]
    expected_history_epoch: Annotated[str, Field(strict=True, min_length=1, max_length=64)] | Annotated[int, Field(strict=True, ge=1)]
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_override_reason(self):
        if self.action in {"run_now", "postpone", "manual"} and not (self.reason or "").strip():
            raise ValueError("An override reason is required")
        return self
