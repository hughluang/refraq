"""Recovery accepts opaque epochs emitted by the authoritative history gate."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from backend.metadata.mirrors.schemas import StrictModel


class RecoveryRequest(StrictModel):
    action: Literal["retry", "run_now", "postpone", "manual", "reconcile_state"]
    expected_history_epoch: Annotated[str, Field(strict=True, min_length=1, max_length=64)] | Annotated[int, Field(strict=True, ge=1)]
    channel_id: str | None = Field(default=None, min_length=1, max_length=64)
    channel_version: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def require_scope(self):
        if self.action in {"run_now", "postpone", "manual", "reconcile_state"} and not (self.reason or "").strip():
            raise ValueError("An override reason is required")
        if self.action == "reconcile_state":
            if self.channel_id is None or self.channel_version is None:
                raise ValueError("Reconciliation requires a Channel version")
        elif self.channel_id is not None or self.channel_version is not None:
            raise ValueError("Channel scope is only valid for reconciliation")
        return self
