"""Response shape for the host occupancy read."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

HostSpan = Literal["hour", "day", "retained"]


class SampleOut(BaseModel):
    t: str
    v: float | None = None


class CpuModeOut(BaseModel):
    mode: str
    samples: list[SampleOut]


class CpuTileOut(BaseModel):
    online_count: int | None = None
    busy_share: float | None = None


class TilesOut(BaseModel):
    cpu: CpuTileOut


class ChartsOut(BaseModel):
    cpu_modes: list[CpuModeOut]
    run_queue: list[SampleOut]


class HostReadOut(BaseModel):
    span: HostSpan
    start: str
    end: str
    step_seconds: int
    tiles: TilesOut
    charts: ChartsOut
