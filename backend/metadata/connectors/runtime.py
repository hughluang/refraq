"""Outbound connector invocation: bind engine + access, then bounded execute."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any, TypeVar

from backend.metadata.connectors.base import (
    ConnectorError,
    EngineConnector,
    SourceEndpoint,
    endpoint_from_access,
)
from backend.metadata.connectors.registry import get_connector

T = TypeVar("T")


@dataclass(frozen=True)
class PreparedEngine:
    """Connector and endpoint resolved from the same access document."""

    connector: EngineConnector
    endpoint: SourceEndpoint


def prepare(*, engine: str, access: dict[str, Any]) -> PreparedEngine:
    """Bind an engine adapter to a SourceEndpoint from one access document."""
    connector = get_connector(engine)
    if connector is None:
        raise ConnectorError(
            "CONNECTOR_UNAVAILABLE",
            f"No connector for engine {engine}",
        )
    return PreparedEngine(
        connector=connector,
        endpoint=endpoint_from_access(engine=engine, access=access),
    )


def run_bounded(fn: Callable[[], T], *, timeout_sec: float) -> T:
    """Run ``fn`` on a worker thread and abort waiting after ``timeout_sec``.

    Do not use ``with ThreadPoolExecutor``: on timeout its ``__exit__`` calls
    ``shutdown(wait=True)`` and would block until the hung connector returns.
    """
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(fn)
        try:
            return future.result(timeout=timeout_sec)
        except FuturesTimeout as exc:
            raise TimeoutError(f"timed out after {timeout_sec}s") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
