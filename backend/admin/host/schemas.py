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


class MemoryTileOut(BaseModel):
    used_bytes: float | None = None
    total_bytes: float | None = None


class SwapTileOut(BaseModel):
    used_bytes: float | None = None
    total_bytes: float | None = None


class FilesystemTileOut(BaseModel):
    mount: str
    type: str
    used_bytes: float | None = None
    total_bytes: float | None = None
    used_share: float | None = None
    free_inodes: float | None = None


class TilesOut(BaseModel):
    cpu: CpuTileOut
    memory: MemoryTileOut
    swap: SwapTileOut
    filesystems: list[FilesystemTileOut]


class FilesystemChartOut(BaseModel):
    mount: str
    type: str
    available: list[SampleOut]
    delta: list[SampleOut]


class DiskChartOut(BaseModel):
    device: str
    busy_share: list[SampleOut]
    queue_length: list[SampleOut]


class PressureSideOut(BaseModel):
    waiting: list[SampleOut]
    stalled: list[SampleOut]


class PressureOut(BaseModel):
    cpu: PressureSideOut
    memory: PressureSideOut
    io: PressureSideOut


class ChartsOut(BaseModel):
    cpu_modes: list[CpuModeOut]
    run_queue: list[SampleOut]
    filesystems: list[FilesystemChartOut]
    disks: list[DiskChartOut]
    pressure: PressureOut


class HostReadOut(BaseModel):
    span: HostSpan
    start: str
    end: str
    step_seconds: int
    tiles: TilesOut
    charts: ChartsOut
