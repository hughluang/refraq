"""Synchronous Source reachability probe (no Job, no persistence)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.metadata.connectors.base import ConnectorError
from backend.metadata.connectors.runtime import prepare, run_bounded
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
) -> ProbeResult:
    try:
        bound = prepare(engine=engine, access=access)
    except ConnectorError as exc:
        raise SourceEngineUnsupported() from exc

    try:
        run_bounded(
            lambda: bound.connector.test_connection(bound.endpoint),
            timeout_sec=PROBE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
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
