"""Context values stay inside the schema published to the Console."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.admin.system_parameters.spec import IntConstraint, StringEnumConstraint
from backend.channel.context import (
    channel_context,
    context_schema,
    platform_context,
    run_context,
)
from backend.channel.template import output_matches


def test_context_values_match_their_schema(monkeypatch) -> None:
    specs = (
        SimpleNamespace(key="keep_days", constraint=IntConstraint(minimum=1)),
        SimpleNamespace(
            key="schedule_timezone",
            constraint=StringEnumConstraint(("UTC", "Asia/Shanghai")),
        ),
    )
    monkeypatch.setattr("backend.channel.context.list_registered_specs", lambda: specs)
    monkeypatch.setattr(
        "backend.channel.context.resolve_int",
        lambda key: SimpleNamespace(value=30 if key == "keep_days" else 0),
    )
    monkeypatch.setattr(
        "backend.channel.context.resolve_str",
        lambda key: SimpleNamespace(value="UTC"),
    )
    started = datetime(2026, 10, 14, 8, 12, 57, tzinfo=timezone.utc)
    channel = SimpleNamespace(id="chn_1", name="Suppliers", description=None, active=True)
    run = SimpleNamespace(
        job_id="job_1",
        target="draft",
        version=None,
        draft_revision=3,
        graph={"settings": {"run_timeout_sec": None, "error_channel_id": None}},
    )
    schemas = context_schema()
    parameters = schemas["platform"]["properties"]["parameters"]["properties"]
    assert parameters == {
        "keep_days": {"type": "integer"},
        "schedule_timezone": {"type": "string"},
    }
    assert output_matches(channel_context(channel, run), schemas["channel"])
    assert output_matches(
        run_context(run, started, {"id": "usr_1", "name": "root"}, "user"),
        schemas["run"],
    )
    assert output_matches(platform_context(started), schemas["platform"])


def test_platform_context_surfaces_registry_failure(monkeypatch) -> None:
    def explode() -> None:
        raise RuntimeError("registry down")

    monkeypatch.setattr("backend.channel.context.list_registered_specs", explode)
    with pytest.raises(RuntimeError, match="registry down"):
        platform_context(datetime(2026, 10, 14, tzinfo=timezone.utc))
