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


class PostgresTileOut(BaseModel):
    backends: float | None = None
    max_connections: float | None = None


class TilesOut(BaseModel):
    cpu: CpuTileOut
    memory: MemoryTileOut
    swap: SwapTileOut
    filesystems: list[FilesystemTileOut]
    postgres: PostgresTileOut


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


class PostgresChartOut(BaseModel):
    backends: list[SampleOut]
    idle_in_transaction: list[SampleOut]
    idle_in_transaction_aborted: list[SampleOut]
    checkpoint_timed: list[SampleOut]
    checkpoint_requested: list[SampleOut]
    checkpoint_write_time: list[SampleOut]
    checkpoint_sync_time: list[SampleOut]
    checkpoint_buffers_written: list[SampleOut]
    temp_files: list[SampleOut]
    temp_bytes: list[SampleOut]


class ChartsOut(BaseModel):
    cpu_modes: list[CpuModeOut]
    run_queue: list[SampleOut]
    filesystems: list[FilesystemChartOut]
    disks: list[DiskChartOut]
    pressure: PressureOut
    postgres: PostgresChartOut


class HostReadOut(BaseModel):
    span: HostSpan
    start: str
    end: str
    step_seconds: int
    tiles: TilesOut
    charts: ChartsOut
