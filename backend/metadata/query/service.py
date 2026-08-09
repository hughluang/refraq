"""Controlled query domain service (HTTP + MCP shared)."""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass
from typing import Any

from backend.admin.audit import persist_audit_event
from backend.core.config import get_settings
from backend.core.errors import AppError
from backend.metadata.connectors.base import (
    ConnectorError,
    QueryResult,
    endpoint_from_access,
)
from backend.metadata.connectors.registry import get_connector
from backend.metadata.errors import (
    JobSourceDisabled,
    QueryFailed,
    QueryRowLimit,
    QueryTimeout,
    SourceEngineUnsupported,
)
from backend.metadata.query.guards import assert_readonly_single_statement
from backend.metadata.sources.access import decrypt_access_blob
from backend.metadata.sources.service import require_source

DEFAULT_MAX_ROWS = 100
_SQL_SUMMARY_MAX = 200


@dataclass(frozen=True)
class QueryOutcome:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    duration_ms: int


def _sql_detail(sql: str, *, max_rows: int, code: str | None = None) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "sql_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(),
        "sql_summary": sql[:_SQL_SUMMARY_MAX],
        "max_rows": max_rows,
    }
    if code is not None:
        detail["code"] = code
    return detail


def _audit(
    *,
    actor_user_id: str | None,
    actor_token_id: str | None,
    source_id: str,
    result: str,
    detail: dict[str, Any],
) -> None:
    persist_audit_event(
        actor_user_id=actor_user_id,
        actor_token_id=actor_token_id,
        resource_type="source",
        resource_id=source_id,
        action="query.run",
        result=result,
        detail=detail,
    )


def run_controlled_query(
    *,
    source_id: str,
    sql: str,
    max_rows: int | None,
    actor_user_id: str | None,
    actor_token_id: str | None,
) -> QueryOutcome:
    settings = get_settings()
    platform_cap = settings.refraq_query_max_rows
    timeout_sec = settings.refraq_query_timeout_sec
    effective_max = DEFAULT_MAX_ROWS if max_rows is None else int(max_rows)
    started = time.perf_counter()

    try:
        if effective_max < 1:
            raise QueryRowLimit(f"max_rows must be at least 1, got {effective_max}")
        if effective_max > platform_cap:
            raise QueryRowLimit(
                f"max_rows {effective_max} exceeds platform cap {platform_cap}"
            )

        source = require_source(source_id)
        if source.status != "active":
            raise JobSourceDisabled("Source is not usable for query")
        if not source.engine or not source.access_ciphertext:
            raise QueryFailed("Source has no access configuration")

        connector = get_connector(source.engine)
        if connector is None:
            raise SourceEngineUnsupported()

        normalized = assert_readonly_single_statement(sql, engine=source.engine)
        access = decrypt_access_blob(source.access_ciphertext)
        endpoint = endpoint_from_access(
            engine=source.engine,
            access=access,
            database_name=source.database_name or "",
            schema_filter=source.schema_filter,
        )

        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(
                connector.run_readonly,
                endpoint,
                normalized,
                max_rows=effective_max,
                timeout_sec=timeout_sec,
            )
            try:
                result: QueryResult = future.result(timeout=timeout_sec)
            except FuturesTimeout as exc:
                raise QueryTimeout(
                    f"Query exceeded the platform timeout of {timeout_sec}s"
                ) from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        duration_ms = int((time.perf_counter() - started) * 1000)
        detail = _sql_detail(sql, max_rows=effective_max)
        detail["duration_ms"] = duration_ms
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            source_id=source_id,
            result="success",
            detail=detail,
        )
        return QueryOutcome(
            columns=result.columns,
            rows=result.rows,
            truncated=result.truncated,
            duration_ms=duration_ms,
        )
    except ConnectorError as exc:
        mapped: AppError = (
            QueryTimeout(exc.message)
            if exc.code == "QUERY_TIMEOUT"
            else QueryFailed(exc.message)
        )
        detail = _sql_detail(sql, max_rows=effective_max, code=mapped.code)
        detail["duration_ms"] = int((time.perf_counter() - started) * 1000)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            source_id=source_id,
            result="failure",
            detail=detail,
        )
        raise mapped from exc
    except AppError as exc:
        detail = _sql_detail(sql, max_rows=effective_max, code=exc.code)
        detail["duration_ms"] = int((time.perf_counter() - started) * 1000)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            source_id=source_id,
            result="failure",
            detail=detail,
        )
        raise
    except Exception as exc:  # noqa: BLE001 — map unexpected driver/runtime errors
        detail = _sql_detail(sql, max_rows=effective_max, code="QUERY_FAILED")
        detail["duration_ms"] = int((time.perf_counter() - started) * 1000)
        _audit(
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            source_id=source_id,
            result="failure",
            detail=detail,
        )
        raise QueryFailed(str(exc)) from exc
