"""Admit or refuse one call to a published inbound path."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl

from starlette.requests import Request
from starlette.responses import Response

from backend.channel.channel_run import dispatch, mint_inbound_run
from backend.channel.errors import (
    ChannelInboundBusy,
    ChannelInboundInactive,
    ChannelInboundInputInvalid,
    ChannelInboundUnauthenticated,
)
from backend.channel.inbound_credentials import get_inbound_credential_store
from backend.channel.inbound_dedup import DedupReplay, get_inbound_dedup_store
from backend.channel.inbound_paths import InboundPathRecord, get_inbound_path_store
from backend.channel.inbound_response import (
    InboundResponseStore,
    get_inbound_response_store,
)
from backend.channel.inbound_rejections import (
    InboundRejectionRecord,
    get_inbound_rejection_store,
    new_inbound_rejection_id,
)
from backend.channel.store import get_channel_store
from backend.core.errors import (
    CODE_HTTP_ERROR,
    CODE_HTTP_METHOD_NOT_ALLOWED,
    CODE_HTTP_NOT_FOUND,
    FIELD_VALUE_INVALID,
    FIELD_VALUE_MISSING,
    ProblemFieldError,
    problem_response,
)
from backend.core.time import format_instant, utc_now
from backend.jobs.store import get_job_store

_RETRY_AFTER = "5"

_MAX_BODY = 1024 * 1024
_KEEP_BODY = 16 * 1024
_TIMESTAMP_WINDOW_SEC = 300
_REJECTION_HEADER_NAMES = frozenset({"authorization", "cookie"})
_SLOT_MARGIN_SEC = 120


class _Body:
    def __init__(self, raw: bytes, *, too_large: bool) -> None:
        self.raw = raw
        self.too_large = too_large


async def receive_inbound(request: Request, hook_path: str) -> Response:
    path_row = get_inbound_path_store().get(hook_path)
    if path_row is None:
        return _not_found()
    channel = get_channel_store().get(path_row.channel_id)
    if channel is None:
        return _not_found()
    node = _published_node(channel.id, path_row.node_id)
    config = _config(node)
    credential = _load_credential(config)
    method = request.method.upper()
    headers = _header_map(request)
    query = _query_map(request)
    if not channel.active:
        raw = await _read_prefix(request, _KEEP_BODY)
        _record(path_row, method, headers, query, credential, "inactive", _kept(raw))
        raise ChannelInboundInactive()
    if node is None:
        return _not_found()
    if not _method_allowed(method, config):
        raw = await _read_prefix(request, _KEEP_BODY)
        _record(
            path_row,
            method,
            headers,
            query,
            credential,
            "method_not_allowed",
            _kept(raw),
        )
        return _method_not_allowed()
    body = await _read_admitted(request)
    if body.too_large:
        _record(path_row, method, headers, query, credential, "body_too_large", None)
        return _too_large()
    now = utc_now()
    if not _credential_ok(credential, headers, query, body.raw, now):
        _record(
            path_row,
            method,
            headers,
            query,
            credential,
            "unauthenticated",
            _kept(body.raw),
        )
        raise ChannelInboundUnauthenticated()
    parsed, raw_text, errors = _interpret(headers.get("content-type"), body.raw, config)
    if errors:
        _record(
            path_row,
            method,
            headers,
            query,
            credential,
            "input_invalid",
            _kept(body.raw),
        )
        raise ChannelInboundInputInvalid(errors)
    response_config = config["response"]
    received_at = format_instant(now)
    event_id = _event_id(config, headers, query, parsed)
    if event_id is not None:
        decision = get_inbound_dedup_store().admit(
            channel_id=channel.id,
            path=path_row.path,
            event_id=event_id,
            received_at=now,
            expires_at=now + timedelta(seconds=config.get("dedup_window_sec", 86400)),
        )
        if isinstance(decision, DedupReplay):
            return _http_from_respond(
                {
                    "status": decision.status,
                    "headers": decision.headers,
                    "body": decision.body,
                }
            )
        if decision == "in_flight":
            _record(
                path_row,
                method,
                headers,
                query,
                credential,
                "duplicate_in_flight",
                _kept(body.raw),
            )
            return _retry_unavailable()
    if _unfinished_inbound(path_row.path) >= config.get("max_in_flight", 10):
        if event_id is not None:
            get_inbound_dedup_store().abandon(
                channel_id=channel.id, path=path_row.path, event_id=event_id
            )
        _record(path_row, method, headers, query, credential, "busy", _kept(body.raw))
        raise ChannelInboundBusy()
    try:
        job, _run = mint_inbound_run(
            channel_id=channel.id,
            channel_name=channel.name,
            path=path_row.path,
            trigger_node_id=path_row.node_id,
            request={
                "method": method,
                "headers": _output_headers(headers, credential),
                "query": _output_query(query, credential),
                "body": parsed,
                "raw_body": raw_text,
                "event_id": event_id,
                "received_at": received_at,
            },
        )
    except Exception:
        if event_id is not None:
            get_inbound_dedup_store().abandon(
                channel_id=channel.id, path=path_row.path, event_id=event_id
            )
        raise
    if event_id is not None:
        get_inbound_dedup_store().attach_job(
            channel_id=channel.id,
            path=path_row.path,
            event_id=event_id,
            job_id=job.id,
        )
    if response_config.get("mode") == "immediate":
        payload = _immediate_payload(response_config, query, parsed)
        if event_id is not None:
            get_inbound_dedup_store().answer(
                channel_id=channel.id,
                path=path_row.path,
                event_id=event_id,
                job_id=job.id,
                status=payload["status"],
                headers=payload["headers"],
                body=payload["body"],
            )
        dispatch(job.id)
        return _http_from_respond(payload)
    return _respond_node_response(job.id, response_config)


def _not_found() -> Response:
    return problem_response(status=404, code=CODE_HTTP_NOT_FOUND, detail="Not Found")


def _method_not_allowed() -> Response:
    return problem_response(
        status=405,
        code=CODE_HTTP_METHOD_NOT_ALLOWED,
        detail="Method Not Allowed",
    )


def _too_large() -> Response:
    return problem_response(status=413, code=CODE_HTTP_ERROR, detail="Payload Too Large")


def _retry_unavailable() -> Response:
    return problem_response(
        status=503,
        code=CODE_HTTP_ERROR,
        detail="Service Unavailable",
        headers={"Retry-After": _RETRY_AFTER},
    )


def _unfinished_inbound(path: str) -> int:
    store = get_job_store()
    _queued, queued = store.list(
        kind="channel_run",
        status="queued",
        trigger_kind="inbound",
        trigger_ref=path,
        limit=0,
    )
    _running, running = store.list(
        kind="channel_run",
        status="running",
        trigger_kind="inbound",
        trigger_ref=path,
        limit=0,
    )
    return queued + running


def _respond_node_response(job_id: str, config: Mapping[str, Any]) -> Response:
    wait_sec = config.get("wait_sec", 5)
    store = get_inbound_response_store()
    store.open(job_id, ttl_sec=wait_sec + _SLOT_MARGIN_SEC)
    deadline = time.monotonic() + wait_sec
    cancel = threading.Event()
    threading.Thread(
        target=_close_slot_at,
        args=(store, job_id, deadline, cancel),
        daemon=True,
    ).start()
    dispatch(job_id)
    payload = _read_until(store, job_id, deadline)
    cancel.set()
    if payload is None:
        store.close(job_id)
        payload = store.read(job_id)
    if payload is None:
        return _fallback_response(config)
    return _http_from_respond(payload)


def _close_slot_at(
    store: InboundResponseStore,
    job_id: str,
    deadline: float,
    cancel: threading.Event,
) -> None:
    remaining = deadline - time.monotonic()
    if remaining > 0 and cancel.wait(remaining):
        return
    store.close(job_id)


def _read_until(
    store: InboundResponseStore, job_id: str, deadline: float
) -> dict[str, Any] | None:
    payload = store.read(job_id)
    if payload is not None:
        return payload
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    return store.wait(job_id, remaining)


def _http_from_respond(payload: Mapping[str, Any]) -> Response:
    return Response(
        content=_encoded_body(payload["body"]),
        status_code=payload["status"],
        headers=payload["headers"],
    )


def _encoded_body(body: Any) -> str:
    if isinstance(body, str):
        return body
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def _fallback_response(config: Mapping[str, Any]) -> Response:
    raw = config.get("fallback")
    fallback = raw if isinstance(raw, dict) else {}
    return Response(
        content=fallback.get("body", ""),
        status_code=fallback.get("status", 503),
        media_type="text/plain",
    )


def _published_node(channel_id: str, node_id: str) -> dict[str, Any] | None:
    versions, _total = get_channel_store().list_versions(channel_id, limit=1, offset=0)
    if not versions:
        return None
    for node in versions[0].graph.get("nodes") or []:
        if isinstance(node, dict) and node.get("id") == node_id:
            return node
    return None


def _config(node: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {}
    config = node.get("config")
    return config if isinstance(config, dict) else {}


def _load_credential(config: Mapping[str, Any]) -> Any:
    credential_id = config.get("credential_id")
    if not isinstance(credential_id, str) or credential_id == "":
        return None
    return get_inbound_credential_store().get(credential_id)


def _method_allowed(method: str, config: Mapping[str, Any]) -> bool:
    if method == "POST":
        return True
    return method == "GET" and config.get("allow_get") is True


def _header_map(request: Request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.headers.items()}


def _query_map(request: Request) -> dict[str, str]:
    found: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        found[str(key)] = str(value)
    return found


async def _read_prefix(request: Request, keep: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if total >= keep:
            continue
        room = keep - total
        piece = chunk[:room]
        chunks.append(piece)
        total += len(piece)
    return b"".join(chunks)


async def _read_admitted(request: Request) -> _Body:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > _MAX_BODY:
                return _Body(b"", too_large=True)
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_BODY:
            return _Body(b"", too_large=True)
        chunks.append(chunk)
    return _Body(b"".join(chunks), too_large=False)


def _kept(raw: bytes) -> str | None:
    if not raw:
        return None
    return raw[:_KEEP_BODY].decode("utf-8", errors="replace")


def _record(
    path_row: InboundPathRecord,
    method: str,
    headers: dict[str, str],
    query: dict[str, str],
    credential: Any,
    reason: str,
    body: str | None,
) -> None:
    get_inbound_rejection_store().insert(
        InboundRejectionRecord(
            id=new_inbound_rejection_id(),
            channel_id=path_row.channel_id,
            node_id=path_row.node_id,
            path=path_row.path,
            received_at=utc_now(),
            reason=reason,
            method=method,
            headers=_rejection_headers(headers, credential),
            query=_rejection_query(query, credential),
            body=body,
        )
    )


def _credential_header_name(credential: Any) -> str | None:
    if credential is None:
        return None
    config = credential.config if isinstance(credential.config, dict) else {}
    if credential.credential_type == "token" and config.get("location") == "header":
        name = config.get("name")
        return name.lower() if isinstance(name, str) and name else None
    if credential.credential_type == "hmac_sha256":
        name = config.get("signature_header")
        return name.lower() if isinstance(name, str) and name else None
    return None


def _credential_query_name(credential: Any) -> str | None:
    if credential is None or credential.credential_type != "token":
        return None
    config = credential.config if isinstance(credential.config, dict) else {}
    if config.get("location") != "query":
        return None
    name = config.get("name")
    return name if isinstance(name, str) and name else None


def _output_headers(headers: dict[str, str], credential: Any) -> dict[str, str]:
    hidden = _credential_header_name(credential)
    return {key: value for key, value in headers.items() if key != hidden}


def _output_query(query: dict[str, str], credential: Any) -> dict[str, str]:
    hidden = _credential_query_name(credential)
    return {key: value for key, value in query.items() if key != hidden}


def _rejection_headers(headers: dict[str, str], credential: Any) -> dict[str, str]:
    hidden = _credential_header_name(credential)
    return {
        key: value
        for key, value in headers.items()
        if key != hidden and key not in _REJECTION_HEADER_NAMES
    }


def _rejection_query(query: dict[str, str], credential: Any) -> dict[str, str]:
    hidden = _credential_query_name(credential)
    return {key: value for key, value in query.items() if key != hidden}


def _credential_ok(
    credential: Any,
    headers: dict[str, str],
    query: dict[str, str],
    raw: bytes,
    now: datetime,
) -> bool:
    if credential is None or not isinstance(credential.secret, str):
        return False
    secret = credential.secret
    if credential.credential_type == "token":
        return _same_secret(_presented_token(credential, headers, query), secret)
    if credential.credential_type == "hmac_sha256":
        return _hmac_ok(credential, secret, headers, raw, now)
    return False


def _presented_token(
    credential: Any, headers: dict[str, str], query: dict[str, str]
) -> str:
    config = credential.config if isinstance(credential.config, dict) else {}
    name = config.get("name")
    if not isinstance(name, str) or name == "":
        return ""
    if config.get("location") == "query":
        value = query.get(name)
        return value if isinstance(value, str) else ""
    return headers.get(name.lower(), "")


def _hmac_ok(
    credential: Any,
    secret: str,
    headers: dict[str, str],
    raw: bytes,
    now: datetime,
) -> bool:
    config = credential.config if isinstance(credential.config, dict) else {}
    signature_name = config.get("signature_header")
    provided = ""
    if isinstance(signature_name, str) and signature_name:
        provided = headers.get(signature_name.lower(), "")
    timestamp_name = config.get("timestamp_header")
    stamp = ""
    if isinstance(timestamp_name, str) and timestamp_name:
        stamp = headers.get(timestamp_name.lower(), "")
        message = stamp.encode("utf-8") + b"." + raw
    else:
        timestamp_name = None
        message = raw
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    if config.get("encoding") == "base64":
        encoded = base64.b64encode(digest).decode("ascii")
    else:
        encoded = digest.hex()
    prefix = config.get("prefix")
    if not isinstance(prefix, str):
        prefix = ""
    matched = _same_secret(provided, f"{prefix}{encoded}")
    if isinstance(timestamp_name, str) and timestamp_name and not _timestamp_fresh(stamp, now):
        return False
    return matched


def _timestamp_fresh(raw: str, now: datetime) -> bool:
    text = raw.strip()
    if text == "" or len(text) > 20 or not text.lstrip("-").isdigit():
        return False
    stamp = int(text)
    return abs(now.timestamp() - stamp) <= _TIMESTAMP_WINDOW_SEC


def _same_secret(provided: str, expected: str) -> bool:
    left = hashlib.sha256(provided.encode("utf-8")).digest()
    right = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(left, right)


def _interpret(
    content_type: str | None, raw: bytes, config: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, str | None, list[ProblemFieldError]]:
    raw_text = _utf8(raw)
    media = _media(content_type)
    if media == "application/json":
        parsed, errors = _parse_json(raw_text)
    elif media == "application/x-www-form-urlencoded":
        parsed, errors = _parse_form(raw_text)
    else:
        return None, raw_text, []
    if errors:
        return None, raw_text, errors
    return parsed, raw_text, _field_errors(config.get("input"), parsed)


def _media(content_type: str | None) -> str:
    if not isinstance(content_type, str):
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def _utf8(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _parse_json(
    text: str | None,
) -> tuple[dict[str, Any] | None, list[ProblemFieldError]]:
    if text is None:
        return None, [_invalid("body")]
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None, [_invalid("body")]
    if not isinstance(value, dict):
        return None, [_invalid("body")]
    return value, []


def _parse_form(
    text: str | None,
) -> tuple[dict[str, Any] | None, list[ProblemFieldError]]:
    if text is None:
        return None, [_invalid("body")]
    parsed: dict[str, Any] = {}
    for key, value in parse_qsl(text, keep_blank_values=True):
        parsed[key] = value
    return parsed, []


def _field_errors(declared: Any, body: dict[str, Any] | None) -> list[ProblemFieldError]:
    if not isinstance(declared, list) or not isinstance(body, dict):
        return []
    errors: list[ProblemFieldError] = []
    for item in declared:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        kind = item.get("type")
        if not isinstance(name, str) or name == "" or not isinstance(kind, str):
            continue
        if name not in body:
            if item.get("required") is True:
                errors.append(_missing(name))
            continue
        if not _type_ok(body[name], kind):
            errors.append(_invalid(name))
    return errors


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    return False


def _missing(field: str) -> ProblemFieldError:
    return ProblemFieldError(
        field=field, code=FIELD_VALUE_MISSING, message="Field required"
    )


def _invalid(field: str) -> ProblemFieldError:
    return ProblemFieldError(
        field=field, code=FIELD_VALUE_INVALID, message="Value is invalid"
    )


def _event_id(
    config: Mapping[str, Any],
    headers: dict[str, str],
    query: dict[str, str],
    body: dict[str, Any] | None,
) -> str | None:
    spec = config.get("event_id")
    if not isinstance(spec, dict):
        return None
    value = _picked(spec, headers, query, body)
    if isinstance(value, str) and value != "":
        return value
    return None


def _picked(
    spec: Mapping[str, Any],
    headers: dict[str, str],
    query: dict[str, str],
    body: dict[str, Any] | None,
) -> Any:
    key = spec.get("key")
    if not isinstance(key, str) or key == "":
        return None
    source = spec.get("from")
    if source == "header":
        return headers.get(key.lower())
    if source == "query":
        return query.get(key)
    if source == "body":
        return _dotted(body, key)
    return None


def _dotted(body: Any, key: str) -> Any:
    current = body
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _immediate_payload(
    config: Mapping[str, Any], query: dict[str, str], body: dict[str, Any] | None
) -> dict[str, Any]:
    spec = config.get("body")
    text = ""
    if isinstance(spec, dict):
        if spec.get("kind") == "static":
            raw = spec.get("text")
            text = raw if isinstance(raw, str) else ""
        elif spec.get("kind") == "echo":
            text = _as_text(_picked(spec, {}, query, body))
    headers = _response_headers(config)
    headers["Content-Type"] = _content_type(config)
    return {"status": _status(config), "headers": headers, "body": text}


def _status(config: Mapping[str, Any]) -> int:
    value = config.get("status", 200)
    if isinstance(value, bool) or not isinstance(value, int):
        return 200
    if value < 100 or value > 599:
        return 200
    return value


def _content_type(config: Mapping[str, Any]) -> str:
    value = config.get("content_type", "application/json")
    if not isinstance(value, str) or value.strip() == "":
        return "application/json"
    return value


def _response_headers(config: Mapping[str, Any]) -> dict[str, str]:
    raw = config.get("headers")
    if not isinstance(raw, dict):
        return {}
    found: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        if key.strip() == "" or key.lower() == "content-type":
            continue
        if "\r" in key or "\n" in key or "\r" in value or "\n" in value:
            continue
        found[key] = value
    return found


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, int, float, bool)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return ""
