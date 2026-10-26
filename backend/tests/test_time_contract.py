"""Contract tests for backend.core.time."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, get_args, get_origin
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ValidationError

from backend.core.time import (
    FixedClock,
    Instant,
    NaiveDateTimeError,
    UtcDateTime,
    ensure_aware_utc,
    format_instant,
    get_clock,
    parse_instant,
    reset_clock,
    resolve_wall_time,
    set_clock,
    utc_now,
    _instant_after,
)


def test_utc_now_is_aware_utc() -> None:
    reset_clock()
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_fixed_clock_freezes_and_resets() -> None:
    fixed = FixedClock(datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc))
    set_clock(fixed)
    assert utc_now() == datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    fixed.advance(timedelta(minutes=5))
    assert utc_now() == datetime(2026, 8, 12, 10, 5, tzinfo=timezone.utc)
    reset_clock()
    assert get_clock() is not fixed


def test_ensure_aware_utc_rejects_naive() -> None:
    with pytest.raises(NaiveDateTimeError):
        ensure_aware_utc(datetime(2026, 1, 1, 12, 0, 0))  # noqa: DTZ001


def test_ensure_aware_utc_normalizes_offset() -> None:
    value = datetime(2026, 1, 1, 20, 0, tzinfo=timezone(timedelta(hours=8)))
    assert ensure_aware_utc(value) == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_format_and_parse_instant_roundtrip() -> None:
    instant = datetime(2026, 8, 12, 2, 0, 0, tzinfo=timezone.utc)
    text = format_instant(instant)
    assert text.endswith("Z")
    assert parse_instant(text) == instant
    assert parse_instant("2026-08-12T10:00:00+08:00") == instant


def test_format_instant_truncates_fractional_seconds_toward_zero() -> None:
    instant = datetime(2026, 8, 12, 2, 0, 5, 900000, tzinfo=timezone.utc)
    assert format_instant(instant) == "2026-08-12T02:00:05Z"


def test_parse_instant_rejects_naive_string() -> None:
    with pytest.raises(ValueError):
        parse_instant("2026-08-12T10:00:00")


@pytest.mark.parametrize(
    "text",
    [
        "2026-08-12T02:00:05.9",
        "2026-08-12T02:00:05",
        "2026-08-12T24:00:00Z",
        "2016-12-31T23:59:60Z",
    ],
)
def test_parse_instant_rejects_offsetless_naive_24h_and_leap_seconds(text: str) -> None:
    with pytest.raises(ValueError):
        parse_instant(text)


def test_parse_instant_keeps_fractional_offset_as_aware_utc() -> None:
    parsed = parse_instant("2026-08-12T10:00:05.9+08:00")
    assert parsed == datetime(2026, 8, 12, 2, 0, 5, 900000, tzinfo=timezone.utc)
    assert parsed.utcoffset() == timedelta(0)


class _InstantModel(BaseModel):
    at: Instant


def test_instant_field_accepts_offset_and_emits_z() -> None:
    model = _InstantModel.model_validate({"at": "2026-08-12T10:00:00+08:00"})
    assert model.at == datetime(2026, 8, 12, 2, 0, tzinfo=timezone.utc)
    dumped = model.model_dump_json()
    assert '"2026-08-12T02:00:00Z"' in dumped
    for mode in ("serialization", "validation"):
        schema = _InstantModel.model_json_schema(mode=mode)
        assert schema["properties"]["at"]["type"] == "string"
        assert schema["properties"]["at"]["format"] == "date-time"


def test_instant_field_rejects_naive() -> None:
    with pytest.raises(ValidationError):
        _InstantModel.model_validate({"at": "2026-08-12T10:00:00"})


def test_utc_datetime_bind_rejects_naive() -> None:
    col = UtcDateTime()
    with pytest.raises(NaiveDateTimeError):
        col.process_bind_param(datetime(2026, 1, 1, 0, 0, 0), dialect=None)  # noqa: DTZ001


def test_utc_datetime_result_normalizes_naive_as_utc() -> None:
    col = UtcDateTime()
    value = col.process_result_value(
        datetime(2026, 1, 1, 0, 0, 0), dialect=None  # noqa: DTZ001
    )
    assert value == datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def test_resolve_wall_time_ambiguous_uses_fold_one() -> None:
    # US Pacific 2025-11-02 01:30 exists twice; second occurrence is fold=1.
    tz = ZoneInfo("America/Los_Angeles")
    resolved = resolve_wall_time(2025, 11, 2, 1, 30, 0, tz)
    assert resolved == datetime(2025, 11, 2, 1, 30, tzinfo=tz, fold=1).astimezone(
        timezone.utc
    )


def test_resolve_wall_time_gap_advances_to_next_legal() -> None:
    # US Pacific 2025-03-09 02:30 does not exist; next legal is 03:00.
    tz = ZoneInfo("America/Los_Angeles")
    resolved = resolve_wall_time(2025, 3, 9, 2, 30, 0, tz)
    local = resolved.astimezone(tz)
    assert (local.hour, local.minute) == (3, 0)


def _export_time_fields():
    path = Path(__file__).resolve().parents[2] / "scripts" / "export_time_fields.py"
    spec = importlib.util.spec_from_file_location("export_time_fields", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _uses_instant(annotation: Any) -> bool:
    if annotation is Instant:
        return True
    if get_origin(annotation) is None:
        return False
    return any(_uses_instant(arg) for arg in get_args(annotation))


def _field_is_instant(field: Any) -> bool:
    # Required Instant fields are unwrapped to AwareDatetime; the validator stays in metadata.
    if any(getattr(meta, "func", None) is _instant_after for meta in field.metadata):
        return True
    return _uses_instant(field.annotation)


def _iter_models():
    seen: set[type] = set()
    stack = list(BaseModel.__subclasses__())
    while stack:
        model = stack.pop()
        if model in seen:
            continue
        seen.add(model)
        stack.extend(model.__subclasses__())
        yield model


def _declares_date_time(node: Any, defs: dict[str, Any], seen: set[str] | None = None) -> bool:
    if not isinstance(node, dict):
        return False
    seen = set() if seen is None else seen
    ref = node.get("$ref")
    if isinstance(ref, str):
        if ref in seen:
            return False
        name = ref.rsplit("/", 1)[-1]
        return _declares_date_time(defs.get(name), defs, seen | {ref})
    if node.get("type") == "string" and node.get("format") == "date-time":
        return True
    if node.get("type") == "array":
        return _declares_date_time(node.get("items"), defs, seen)
    for key in ("anyOf", "oneOf", "allOf"):
        if key not in node:
            continue
        branches = [
            branch
            for branch in node[key]
            if isinstance(branch, dict) and branch.get("type") != "null"
        ]
        return bool(branches) and all(
            _declares_date_time(branch, defs, seen) for branch in branches
        )
    return False


def _annotation_is_datetime(annotation: Any) -> bool:
    if annotation is datetime:
        return True
    if get_origin(annotation) is None:
        return False
    return any(_annotation_is_datetime(arg) for arg in get_args(annotation))


def datetime_fields_missing_instant(model: type[BaseModel]) -> list[str]:
    """Datetime response fields the marked-only Instant walk does not visit."""
    missing: list[str] = []
    for name, field in model.model_fields.items():
        if field.exclude or _field_is_instant(field):
            continue
        if _annotation_is_datetime(field.annotation):
            missing.append(name)
    return missing


def test_positive_checks_and_count_floor_miss_unmarked_datetime_response() -> None:
    from backend.main import app

    class UnmarkedResponse(BaseModel):
        occurred_at: datetime

    app.openapi()
    positive = [
        name
        for name, field in UnmarkedResponse.model_fields.items()
        if _field_is_instant(field) and not field.exclude
    ]
    marked = sum(
        1
        for model in _iter_models()
        for field in model.model_fields.values()
        if _field_is_instant(field) and not field.exclude
    )
    schema = UnmarkedResponse.model_json_schema(mode="serialization")
    assert positive == []
    assert marked >= 67
    assert schema["properties"]["occurred_at"]["format"] == "date-time"
    assert datetime_fields_missing_instant(UnmarkedResponse) == ["occurred_at"]


def test_instant_fields_declare_date_time() -> None:
    from backend.main import app

    spec = app.openapi()
    components = spec["components"]["schemas"]
    missing: list[str] = []
    local_checked = 0
    published_checked = 0
    for model in _iter_models():
        for name, field in model.model_fields.items():
            if not _field_is_instant(field) or field.exclude:
                continue
            local_checked += 1
            local = model.model_json_schema(mode="serialization")
            prop = (local.get("properties") or {}).get(name)
            if not _declares_date_time(prop, local.get("$defs") or {}):
                missing.append(f"{model.__module__}.{model.__name__}.{name}")
                continue
            published = components.get(model.__name__)
            if not isinstance(published, dict):
                continue
            published_checked += 1
            published_prop = (published.get("properties") or {}).get(name)
            if not _declares_date_time(published_prop, components):
                missing.append(f"openapi {model.__name__}.{name}")
    assert missing == [], missing
    # Already-marked fields only. A count floor does not notice an unmarked
    # datetime response field; that gap is test_positive_checks_and_count_floor_miss_unmarked_datetime_response.
    assert local_checked >= 67, local_checked
    assert published_checked > 0


def test_exported_time_fields_match_openapi() -> None:
    """Derivation still sees OpenAPI Instants. The console does not load that table."""
    from backend.main import app

    module = _export_time_fields()
    derived = module.derive_response_time_fields(app.openapi())
    assert "items[].started_at" in derived["GET /channels/{channel_id}/runs"]
    assert "items[].created_at" in derived["GET /channels/{channel_id}/runs"]
    assert "grants[].valid_until" in derived["GET /entities/{entity_id}/access"]
    assert "next_run_ats[]" in derived["POST /schedules/cron-preview"]
    frontend = Path(__file__).resolve().parents[2] / "frontend" / "src"
    runtime_sources = [
        path.read_text(encoding="utf-8")
        for path in frontend.rglob("*")
        if path.suffix in {".ts", ".tsx"}
    ]
    assert all("api-time-fields.generated.json" not in source for source in runtime_sources)


def test_derivation_rejects_dynamic_keys_that_hold_instants() -> None:
    module = _export_time_fields()
    spec = {
        "components": {
            "schemas": {
                "Row": {
                    "type": "object",
                    "additionalProperties": {"type": "string", "format": "date-time"},
                }
            }
        },
        "paths": {
            "/rows": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Row"}
                                }
                            }
                        }
                    }
                }
            }
        },
    }
    with pytest.raises(module.UnresolvedTimeSchema):
        module.derive_response_time_fields(spec)
