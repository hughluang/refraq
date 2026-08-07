"""Synchronous Source reachability probe (no Job, no persistence)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any

from backend.metadata.connectors.base import ConnectorError, endpoint_from_access
from backend.metadata.connectors.registry import get_connector
from backend.metadata.errors import SourceEngineUnsupported

PROBE_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    code: str | None = None
    message: str | None = None


def run_source_probe(
    *,
    engine: str,
    access: dict[str, Any],
    database_name: str,
) -> ProbeResult:
    connector = get_connector(engine)
    if connector is None:
        raise SourceEngineUnsupported()

    endpoint = endpoint_from_access(
        engine=engine,
        access=access,
        database_name=database_name,
        schema_filter=None,
    )

    # Do not use `with ThreadPoolExecutor`: on timeout its __exit__ calls
    # shutdown(wait=True) and would block until the hung connector returns.
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(connector.test_connection, endpoint)
        try:
            future.result(timeout=PROBE_TIMEOUT_SECONDS)
        except FuturesTimeout:
            return ProbeResult(
                ok=False,
                code="SOURCE_TEST_TIMEOUT",
                message=f"Source probe timed out after {PROBE_TIMEOUT_SECONDS}s",
            )
        except ConnectorError as exc:
            return ProbeResult(
                ok=False,
                code="SOURCE_TEST_FAILED",
                message=exc.message,
            )
        except Exception as exc:  # noqa: BLE001 — map unexpected driver errors
            return ProbeResult(
                ok=False,
                code="SOURCE_TEST_FAILED",
                message=str(exc),
            )
        return ProbeResult(ok=True)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
