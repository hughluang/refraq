"""HTTP request action node type."""

from __future__ import annotations

import base64
import json
import re
import ssl
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping
from urllib.parse import quote, urljoin, urlsplit

import httpx

from backend.channel import node_support
from backend.channel.http_accounts import HttpAccountRecord, get_http_account_store
from backend.channel.node_support import render_field
from backend.channel.nodes.spec import (
    ERROR_OUTPUT,
    MAIN_INPUT,
    MAIN_OUTPUT,
    EngineHooks,
    NodeResult,
    NodeType,
    OutputView,
    Problem,
    ReferenceResolver,
    object_schema,
)
from backend.channel.parameters import channel_http_response_max_bytes
from backend.channel.template import TemplateSyntaxError, parse

__all__ = ["NODE_TYPE"]

_TEXT: dict[str, Any] = {"type": "string"}
# JSON mode can render any JSON value. Raw mode renders with _TEXT instead.
_ANY: dict[str, Any] = {
    "type": ["object", "array", "string", "number", "boolean", "null"],
}
_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
_NO_BODY = frozenset({"GET", "HEAD"})
_FORBIDDEN = frozenset(
    {
        "authorization",
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "upgrade",
        "te",
        "trailer",
        "proxy-authorization",
        "proxy-connection",
    }
)
_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_URL_LIMIT = 8192
_RETRY_CAP = 3600
_DEFAULT_TIMEOUT = 30
_DEFAULT_REDIRECTS = 5
_READ_CHUNK = 65536


class _TimedOut(Exception):
    pass


class _HeaderMap:
    def __init__(self) -> None:
        self._items: list[tuple[str, str]] = []

    def set(self, name: str, value: str) -> None:
        key = name.lower()
        self._items = [item for item in self._items if item[0].lower() != key]
        self._items.append((name, value))

    def items(self) -> list[tuple[str, str]]:
        return list(self._items)


def _fail(
    message: str,
    detail: dict[str, Any] | None = None,
    *,
    wait: float | None = None,
) -> NodeResult:
    return NodeResult(
        status="failed",
        error_code="CHANNEL_NODE_FAILED",
        error_message=message,
        error_detail=detail,
        minimum_wait_sec=wait,
    )


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _optional_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _record_url(url: str) -> None:
    capture = node_support._active.get()
    if capture is not None:
        capture.record_value("url", url)


def _append_query(url: str, pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return url
    encoded = "&".join(
        f"{quote(name, safe='')}={quote(value, safe='')}" for name, value in pairs
    )
    base, marker, fragment = url.partition("#")
    separator = "&" if "?" in base else "?"
    joined = f"{base}{separator}{encoded}"
    if marker:
        return f"{joined}#{fragment}"
    return joined


def _is_absolute_http(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    try:
        parts.port
    except ValueError:
        return False
    return True


def _origin(url: str) -> str:
    parts = urlsplit(url)
    host = parts.hostname
    port = parts.port
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    shown = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown}:{port}"


def _host(url: str) -> str:
    return urlsplit(url).hostname


def _account(config: Mapping[str, Any]) -> tuple[HttpAccountRecord | None, NodeResult | None]:
    account_id = config.get("http_account_id")
    if account_id is None:
        return None, None
    if not isinstance(account_id, str):
        return None, _fail("HTTP Account was not found")
    record = get_http_account_store().get(account_id)
    if record is None:
        return None, _fail("HTTP Account was not found")
    return record, None


def _render_pairs(
    hooks: EngineHooks,
    items: Any,
    key: str,
) -> tuple[list[tuple[str, str]] | None, NodeResult | None]:
    if items is None:
        return [], None
    if not isinstance(items, list):
        return None, _fail(f"{key} must be a list")
    pairs: list[tuple[str, str]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            return None, _fail(f"{key} item must be an object")
        name, failure = render_field(
            hooks, item.get("name"), _TEXT, path=f"{key}.{index}.name"
        )
        if failure is not None:
            return None, failure
        value, failure = render_field(
            hooks, item.get("value"), _TEXT, path=f"{key}.{index}.value"
        )
        if failure is not None:
            return None, failure
        pairs.append((str(name), str(value)))
    return pairs, None


def _header_problem(pairs: list[tuple[str, str]]) -> NodeResult | None:
    for name, value in pairs:
        if any(char in value for char in ("\r", "\n", "\x00")):
            return _fail("Header value contains a line break or NUL")
        if not _TOKEN.fullmatch(name) or not 1 <= len(name) <= 128:
            return _fail("Header name must be a token")
        if name.lower() in _FORBIDDEN:
            return _fail("Header name is not allowed")
    return None


def _encode_body(
    value: Any,
    mode: str,
) -> tuple[bytes | None, NodeResult | None]:
    if mode == "raw":
        return value.encode("utf-8"), None
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None, _fail("JSON body cannot be encoded")
    return encoded, None


def _content_type_value(
    hooks: EngineHooks,
    config: Mapping[str, Any],
    mode: str,
) -> tuple[str | None, NodeResult | None]:
    raw = config.get("content_type")
    rendered: str | None = None
    if not _blank(raw):
        value, failure = render_field(hooks, raw, _TEXT, path="content_type")
        if failure is not None:
            return None, failure
        rendered = value
    text = rendered if isinstance(rendered, str) and rendered.strip() else ""
    if mode == "raw":
        if not text:
            return None, _fail("Content type is required for a raw body")
        return rendered, None
    return text and rendered or "application/json", None


def _prepare(
    config: Mapping[str, Any],
    hooks: EngineHooks,
    cap: int,
) -> tuple[dict[str, Any] | None, NodeResult | None]:
    method = config.get("method")
    if method not in _METHODS:
        return None, _fail("HTTP method is not supported")
    url, failure = render_field(hooks, config.get("url"), _TEXT, path="url")
    if failure is not None:
        return None, failure
    query, failure = _render_pairs(hooks, config.get("query"), "query")
    if failure is not None or query is None:
        return None, failure
    headers, failure = _render_pairs(hooks, config.get("headers"), "headers")
    if failure is not None or headers is None:
        return None, failure
    problem = _header_problem(headers)
    if problem is not None:
        return None, problem
    mode = config.get("body_mode") or "json"
    if mode not in {"json", "raw"}:
        return None, _fail("Body mode is not supported")
    body_source = config.get("body")
    encoded: bytes | None = None
    content_type: str | None = None
    if not _blank(body_source):
        if method in _NO_BODY:
            return None, _fail("GET and HEAD cannot send a body")
        schema = _TEXT if mode == "raw" else _ANY
        rendered_body, failure = render_field(hooks, body_source, schema, path="body")
        if failure is not None:
            return None, failure
        encoded, failure = _encode_body(rendered_body, mode)
        if failure is not None:
            return None, failure
        if encoded is not None and len(encoded) > cap:
            return None, _fail("Request body exceeds the size cap")
        content_type, failure = _content_type_value(hooks, config, mode)
        if failure is not None:
            return None, failure
    recorded = _append_query(str(url), query)
    _record_url(recorded)
    if len(recorded) > _URL_LIMIT:
        return None, _fail("URL exceeds 8192 characters")
    if not _is_absolute_http(recorded):
        return None, _fail("URL is not an absolute http or https URL")
    return {
        "method": method,
        "recorded": recorded,
        "headers": headers,
        "body": encoded,
        "content_type": content_type,
        "timeout_sec": _optional_int(config.get("timeout_sec"), _DEFAULT_TIMEOUT),
        "max_redirects": _optional_int(config.get("max_redirects"), _DEFAULT_REDIRECTS),
    }, None


def _request_headers(
    account: HttpAccountRecord | None,
    *,
    drop_account: bool,
    node_headers: list[tuple[str, str]],
    content_type: str | None,
) -> list[tuple[str, str]]:
    headers = _HeaderMap()
    if account is not None and not drop_account:
        for name, value in account.headers:
            headers.set(name, value)
        if account.auth_type == "bearer" and account.secret:
            headers.set("Authorization", f"Bearer {account.secret}")
        elif (
            account.auth_type == "basic"
            and account.username is not None
            and account.secret is not None
        ):
            token = base64.b64encode(
                f"{account.username}:{account.secret}".encode("utf-8")
            ).decode("ascii")
            headers.set("Authorization", f"Basic {token}")
    for name, value in node_headers:
        headers.set(name, value)
    if content_type is not None:
        headers.set("Content-Type", content_type)
    return headers.items()


def _credential_problem(account: HttpAccountRecord | None) -> NodeResult | None:
    if account is None:
        return None
    if account.auth_type == "bearer" and not account.secret:
        return _fail("HTTP Account credential is missing")
    if account.auth_type == "basic" and (
        account.username is None or account.secret is None
    ):
        return _fail("HTTP Account credential is missing")
    return None


def _transport(kind: str, host: str) -> NodeResult:
    if kind == "timeout":
        message = f"Timed out calling {host}"
    elif kind == "tls":
        message = f"TLS verification failed for {host}"
    else:
        message = f"Connection failed for {host}"
    return _fail(message)


def _is_tls(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _read(
    method: str,
    url: str,
    headers: list[tuple[str, str]],
    body: bytes | None,
    timeout: float,
    deadline: float,
    cap: int,
) -> tuple[int, list[tuple[str, str]], bytes | None, int | None]:
    over: tuple[int, list[tuple[str, str]], int] | None = None
    try:
        with httpx.Client(
            verify=True,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(timeout),
        ) as client:
            client.cookies.clear()
            with client.stream(
                method,
                url,
                headers=headers,
                content=body,
                follow_redirects=False,
            ) as response:
                status = response.status_code
                pairs = list(response.headers.multi_items())
                raw = bytearray()
                for chunk in response.iter_bytes(_READ_CHUNK):
                    if time.monotonic() >= deadline:
                        raise _TimedOut()
                    raw.extend(chunk)
                    if len(raw) > cap:
                        over = (status, pairs, len(raw))
                        break
                else:
                    return status, pairs, bytes(raw), None
    except httpx.HTTPError:
        if over is None:
            raise
        return over[0], over[1], None, over[2]
    return over[0], over[1], None, over[2]


def _join_headers(pairs: list[tuple[str, str]]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for name, value in pairs:
        key = name.lower()
        if key not in grouped:
            order.append(key)
            grouped[key] = []
        grouped[key].append(value)
    joined: dict[str, str] = {}
    for key in order:
        values = grouped[key]
        if key == "set-cookie":
            joined[key] = values[-1]
        else:
            joined[key] = ", ".join(values)
    return joined


def _json_media(content_type: str | None) -> bool:
    if not content_type:
        return False
    media = content_type.split(";", 1)[0].strip().lower()
    return "application/json" in media or media.endswith("+json")


def _retry_delay(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return float(int(text))
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment - datetime.now(timezone.utc)).total_seconds()


def _retry_after(status: int, pairs: list[tuple[str, str]]) -> int | float | None:
    if status not in {429, 503}:
        return None
    raw = next((value for name, value in pairs if name.lower() == "retry-after"), None)
    if raw is None:
        return None
    delay = _retry_delay(raw)
    if delay is None:
        return None
    if delay < 0:
        delay = 0
    if delay > _RETRY_CAP:
        delay = _RETRY_CAP
    if delay == int(delay):
        return int(delay)
    return delay


def _attach_retry(
    status: int,
    pairs: list[tuple[str, str]],
    detail: dict[str, Any],
) -> float | None:
    delay = _retry_after(status, pairs)
    if delay is None:
        return None
    detail["retry_after_sec"] = delay
    return float(delay)


def _interpret(
    status: int,
    pairs: list[tuple[str, str]],
    raw: bytes,
) -> dict[str, Any] | NodeResult:
    headers = _join_headers(pairs)
    if raw == b"":
        body: Any = None
    elif _json_media(headers.get("content-type")):
        try:
            body = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            return _fail("Response body is not valid UTF-8", {"status_code": status})
        except json.JSONDecodeError:
            return _fail("Response body is not JSON", {"status_code": status})
    else:
        try:
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _fail("Response body is not valid UTF-8", {"status_code": status})
    return {"status_code": status, "headers": headers, "body": body}


def _from_response(
    status: int,
    pairs: list[tuple[str, str]],
    raw: bytes,
    *,
    message: str | None = None,
) -> NodeResult:
    interpreted = _interpret(status, pairs, raw)
    if isinstance(interpreted, NodeResult):
        detail = dict(interpreted.error_detail or {})
        wait = _attach_retry(status, pairs, detail)
        interpreted.error_detail = detail
        interpreted.minimum_wait_sec = wait
        return interpreted
    if message is None and 200 <= status <= 299:
        return NodeResult(status="succeeded", output=interpreted)
    detail = {"status_code": status, "body": interpreted["body"]}
    wait = _attach_retry(status, pairs, detail)
    return _fail(message or f"HTTP {status}", detail, wait=wait)


def _location(pairs: list[tuple[str, str]]) -> str | None:
    raw = next((value for name, value in pairs if name.lower() == "location"), None)
    if raw is None:
        return None
    text = raw.strip()
    return text or None


def _exchange(
    prepared: Mapping[str, Any],
    account: HttpAccountRecord | None,
    cap: int,
) -> NodeResult:
    recorded = str(prepared["recorded"])
    recorded_origin = _origin(recorded)
    if account is not None and account.allowed_origins:
        if recorded_origin not in account.allowed_origins:
            return _fail("Origin is not allowed")
    problem = _credential_problem(account)
    if problem is not None:
        return problem
    url = _append_query(recorded, list(account.query) if account is not None else [])
    method = str(prepared["method"])
    body = prepared["body"] if isinstance(prepared["body"], bytes) else None
    content_type = prepared["content_type"] if isinstance(prepared["content_type"], str) else None
    node_headers = list(prepared["headers"])
    timeout_sec = int(prepared["timeout_sec"])
    max_redirects = int(prepared["max_redirects"])
    deadline = time.monotonic() + timeout_sec
    drop_account = False
    followed = 0
    while True:
        host = _host(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _transport("timeout", host)
        headers = _request_headers(
            account,
            drop_account=drop_account,
            node_headers=node_headers,
            content_type=content_type if body is not None else None,
        )
        try:
            status, pairs, raw, oversized = _read(
                method,
                url,
                headers,
                body,
                remaining,
                deadline,
                cap,
            )
        except _TimedOut:
            return _transport("timeout", host)
        except httpx.TimeoutException:
            return _transport("timeout", host)
        except httpx.HTTPError as exc:
            kind = "tls" if _is_tls(exc) else "connection"
            return _transport(kind, host)
        if oversized is not None:
            detail: dict[str, Any] = {"status_code": status, "body_bytes": oversized}
            wait = _attach_retry(status, pairs, detail)
            return _fail("Response body exceeds the size cap", detail, wait=wait)
        assert raw is not None
        if 300 <= status < 400:
            if followed >= max_redirects:
                return _from_response(status, pairs, raw)
            location = _location(pairs)
            if location is None:
                return _from_response(
                    status,
                    pairs,
                    raw,
                    message="Redirect is missing a Location",
                )
            target = urljoin(url, location)
            if not _is_absolute_http(target):
                return _from_response(
                    status,
                    pairs,
                    raw,
                    message="Redirect URL is not absolute http or https",
                )
            target_origin = _origin(target)
            if target_origin != recorded_origin:
                drop_account = True
            if status == 303:
                method = "GET"
                body = None
                content_type = None
            url = target
            followed += 1
            continue
        return _from_response(status, pairs, raw)


def _execute(node: Mapping[str, Any], hooks: EngineHooks) -> NodeResult:
    config = node.get("config") or {}
    cap = channel_http_response_max_bytes()
    account, failure = _account(config)
    if failure is not None:
        return failure
    prepared, failure = _prepare(config, hooks, cap)
    if failure is not None:
        return failure
    return _exchange(prepared, account, cap)


def _parse_problem(problems: list[Problem], value: Any, path: tuple[str | int, ...]) -> None:
    if not isinstance(value, str):
        return
    try:
        parse(value)
    except TemplateSyntaxError as exc:
        problems.append(Problem("CHANNEL_NODE_CONFIG_INVALID", str(exc), path=path))


def _check(config: Mapping[str, Any], resolver: ReferenceResolver) -> list[Problem]:
    del resolver
    problems: list[Problem] = []
    account_id = config.get("http_account_id")
    if isinstance(account_id, str) and get_http_account_store().get(account_id) is None:
        problems.append(
            Problem(
                "CHANNEL_REFERENCE_UNRESOLVED",
                "HTTP Account was not found",
                path=("http_account_id",),
            )
        )
    _parse_problem(problems, config.get("url"), ("url",))
    query = config.get("query")
    if isinstance(query, list):
        for index, item in enumerate(query):
            if not isinstance(item, dict):
                continue
            _parse_problem(problems, item.get("name"), ("query", index, "name"))
            _parse_problem(problems, item.get("value"), ("query", index, "value"))
    headers = config.get("headers")
    if isinstance(headers, list):
        for index, item in enumerate(headers):
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            _parse_problem(problems, name, ("headers", index, "name"))
            _parse_problem(problems, item.get("value"), ("headers", index, "value"))
            if isinstance(name, str) and "{{" not in name:
                if not _TOKEN.fullmatch(name):
                    problems.append(
                        Problem(
                            "CHANNEL_NODE_CONFIG_INVALID",
                            "Header name must be a token",
                            path=("headers", index, "name"),
                        )
                    )
                elif name.lower() in _FORBIDDEN:
                    problems.append(
                        Problem(
                            "CHANNEL_NODE_CONFIG_INVALID",
                            "Header name is not allowed",
                            path=("headers", index, "name"),
                        )
                    )
    body = config.get("body")
    if not _blank(body):
        _parse_problem(problems, body, ("body",))
    content_type = config.get("content_type")
    if not _blank(content_type):
        _parse_problem(problems, content_type, ("content_type",))
    method = config.get("method")
    if method in _NO_BODY and not _blank(body):
        problems.append(
            Problem(
                "CHANNEL_NODE_CONFIG_INVALID",
                "GET and HEAD cannot send a body",
                path=("body",),
            )
        )
    mode = config.get("body_mode") or "json"
    if mode == "raw" and not _blank(body) and _blank(content_type):
        problems.append(
            Problem(
                "CHANNEL_NODE_CONFIG_INVALID",
                "Content type is required for a raw body",
                path=("content_type",),
            )
        )
    return problems


def _pair_schema(
    name_limit: int,
    value_limit: int,
    *,
    name_min: int | None = None,
) -> dict[str, Any]:
    name_schema: dict[str, Any] = {
        "type": "string",
        "maxLength": name_limit,
        "title": "Name",
        "description": "Template rendered to the name.",
        "x-refraq-template": _TEXT,
    }
    if name_min is not None:
        name_schema["minLength"] = name_min
    return object_schema(
        {
            "name": name_schema,
            "value": {
                "type": "string",
                "maxLength": value_limit,
                "title": "Value",
                "description": "Template rendered to the value.",
                "x-refraq-template": _TEXT,
            },
        },
        ["name", "value"],
    )


NODE_TYPE = NodeType(
    type_id="action.http",
    family="action",
    label="HTTP request",
    summary="Sends one HTTP request and returns the response.",
    description=(
        "Renders one URL and sends one request when this node runs. "
        "A status from 200 through 299 returns the status code, headers, and body. "
        "Any other result fails this node."
    ),
    trigger=False,
    inputs=(MAIN_INPUT,),
    outputs=(MAIN_OUTPUT, ERROR_OUTPUT),
    config_schema=object_schema(
        {
            "method": {
                "type": "string",
                "enum": list(_METHODS),
                "title": "Method",
                "description": "HTTP method for this request.",
            },
            "url": {
                "type": "string",
                "minLength": 1,
                "maxLength": _URL_LIMIT,
                "title": "URL",
                "description": "Absolute http or https address. One template, including the path.",
                "x-refraq-template": _TEXT,
            },
            "query": {
                "type": "array",
                "maxItems": 32,
                "title": "Query",
                "description": "Parameters appended to the URL. Names and values are templates.",
                "items": _pair_schema(2048, 2048),
            },
            "headers": {
                "type": "array",
                "maxItems": 32,
                "title": "Headers",
                "description": "Headers sent with the request. Names and values are templates.",
                "items": _pair_schema(128, 4096, name_min=1),
            },
            "body_mode": {
                "type": "string",
                "enum": ["json", "raw"],
                "default": "json",
                "title": "Body mode",
                "description": "json sends a JSON value. raw sends the rendered text.",
            },
            "body": {
                "type": "string",
                "title": "Body",
                "description": (
                    "Template for the request body. Blank sends no body. "
                    "JSON mode renders any JSON value. Raw mode renders text."
                ),
                "x-refraq-template": _TEXT,
            },
            "content_type": {
                "type": "string",
                "title": "Content type",
                "description": (
                    "Template for the body Content-Type. "
                    "Required for a non-blank raw body. "
                    "Blank in JSON mode means application/json."
                ),
                "x-refraq-template": _TEXT,
            },
            "http_account_id": {
                "type": ["string", "null"],
                "minLength": 1,
                "title": "HTTP Account",
                "description": "Optional account for auth, static headers, and secret query parameters.",
                "x-refraq-ref": "http_account",
            },
            "timeout_sec": {
                "type": ["integer", "null"],
                "minimum": 1,
                "maximum": 120,
                "default": _DEFAULT_TIMEOUT,
                "title": "Timeout",
                "description": "Seconds for the whole exchange. Blank uses 30.",
            },
            "max_redirects": {
                "type": ["integer", "null"],
                "minimum": 0,
                "maximum": 10,
                "default": _DEFAULT_REDIRECTS,
                "title": "Redirects",
                "description": "How many redirects to follow. Blank uses 5. Zero does not follow.",
            },
        },
        ["method", "url"],
    ),
    output_view=OutputView(kind="record"),
    execute=_execute,
    check=_check,
)
