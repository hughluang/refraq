"""For and Batch Read rounds through ContainerSpec.run and a fake Container Body."""

from __future__ import annotations

import importlib
from typing import Any, Mapping

import pytest

from backend.channel.nodes.spec import NodeResult
from backend.channel.nodes.volume.batch_read import NODE_TYPE as BATCH_READ
from backend.tests.channel_hooks_fake import FakeHooks

FOR = importlib.import_module("backend.channel.nodes.volume.for").NODE_TYPE


class _Scripted:
    """Returns one body output per round and records the step and record."""

    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = outputs
        self.steps: list[Any] = []
        self.records: list[Any] = []

    def run_round(self, step: Any, *, record: Any = None) -> dict[str, Any]:
        self.steps.append(step)
        self.records.append(record)
        return self.outputs[len(self.steps) - 1]

    def evaluate_round_template(
        self, path: str, schema: Mapping[str, Any]
    ) -> tuple[Any, NodeResult | None]:
        raise AssertionError(path)


def _for_node(items: str) -> dict[str, Any]:
    return {"id": "walk", "config": {"items": items}}


def test_for_run_steps_each_element_and_returns_body_outputs() -> None:
    body = _Scripted([{"step": {"n": 1}}, {"step": {"n": 2}}])
    result = FOR.container.run(_for_node('["a", "b"]'), FakeHooks(), body)
    assert result.status == "succeeded"
    assert result.ports == frozenset({"done"})
    assert body.steps == [
        {"current": "a", "index": 0, "count": 2},
        {"current": "b", "index": 1, "count": 2},
    ]
    assert body.records == [None, None]
    assert result.output == {
        "current": "b",
        "index": 1,
        "count": 2,
        "iterations": [{"step": {"n": 1}}, {"step": {"n": 2}}],
    }


def test_for_run_skips_an_empty_list() -> None:
    body = _Scripted([])
    result = FOR.container.run(_for_node("[]"), FakeHooks(), body)
    assert result.status == "succeeded"
    assert result.ports == frozenset({"done"})
    assert body.steps == []
    assert result.output == {
        "current": None,
        "index": None,
        "count": 0,
        "iterations": [],
    }


def test_for_run_rejects_the_item_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.channel.nodes.volume.for.ITEM_LIMIT", 1)
    body = _Scripted([])
    result = FOR.container.run(_for_node("[1, 2]"), FakeHooks(), body)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_ITEM_LIMIT_EXCEEDED"
    assert result.error_message == "Use Materialize or Dataset Query, then Batch Read."
    assert body.steps == []


def test_for_run_reports_the_for_volume_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.channel.variables import value_size

    record = {"step": {"blob": "x" * 30}}
    monkeypatch.setattr(
        "backend.channel.iteration_volume.ITERATION_VOLUME_MAX_BYTES",
        value_size([record]) - 1,
    )
    body = _Scripted([record])
    result = FOR.container.run(_for_node('["a", "b"]'), FakeHooks(), body)
    assert result.status == "failed"
    assert result.error_code == "CHANNEL_ITERATION_VOLUME_EXCEEDED"
    assert result.error_message == (
        "For iteration output exceeds 16 MiB. Read the items in batches."
    )
    assert result.output is None
    assert len(body.steps) == 1
    assert body.records == [None]


def test_for_run_lets_a_body_exception_propagate() -> None:
    class _Boom:
        def run_round(self, step: Any, *, record: Any = None) -> dict[str, Any]:
            del step, record
            raise RuntimeError("round stopped")

        def evaluate_round_template(
            self, path: str, schema: Mapping[str, Any]
        ) -> tuple[Any, NodeResult | None]:
            raise AssertionError(path)

    with pytest.raises(RuntimeError, match="round stopped"):
        FOR.container.run(_for_node("[1]"), FakeHooks(), _Boom())


def _batch_node(*, batch_size: int | None = None, total: int = 0) -> dict[str, Any]:
    dataset = (
        '{"dataset_id":"dset","columns":[{"name":"n","type":"integer"}],'
        f'"count":{total}' + "}"
    )
    config: dict[str, Any] = {"dataset": dataset}
    if batch_size is not None:
        config["batch_size"] = batch_size
    return {"id": "batch", "config": config}


def test_batch_read_run_fetches_the_next_page_after_the_round_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.channel.nodes.volume.batch_read as batch_read
    from backend.tests.test_channel_engine import _plant_dataset

    trace: list[tuple[str, int]] = []
    pages = {
        0: [{"_ord": 1, "n": 1}, {"_ord": 2, "n": 2}],
        2: [{"_ord": 3, "n": 3}],
    }

    def page(relation: str, *, after_ord: int, limit: int) -> list[dict[str, Any]]:
        del relation
        assert limit == 2
        trace.append(("page", after_ord))
        return [dict(row) for row in pages[after_ord]]

    _plant_dataset(monkeypatch, batch_read, row_count=3, page=page)

    class _Body:
        def __init__(self) -> None:
            self.steps: list[Any] = []
            self.records: list[Any] = []

        def run_round(self, step: Any, *, record: Any = None) -> dict[str, Any]:
            trace.append(("round", step["index"]))
            self.steps.append(step)
            self.records.append(record)
            return {"step": {"rows": step["rows"]}}

        def evaluate_round_template(
            self, path: str, schema: Mapping[str, Any]
        ) -> tuple[Any, NodeResult | None]:
            raise AssertionError(path)

    body = _Body()
    result = BATCH_READ.container.run(
        _batch_node(batch_size=2, total=3), FakeHooks(), body
    )
    assert result.status == "succeeded"
    assert result.ports == frozenset({"done"})
    assert trace == [("page", 0), ("round", 0), ("page", 2), ("round", 1)]
    assert body.records == [None, None]
    assert body.steps == [
        {"rows": [{"n": 1}, {"n": 2}], "index": 0, "count": 2, "total": 3},
        {"rows": [{"n": 3}], "index": 1, "count": 2, "total": 3},
    ]
    assert result.output == {"count": 2, "total": 3, "batch_size": 2}
    assert "iterations" not in result.output


def test_batch_read_run_skips_an_empty_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.channel.nodes.volume.batch_read as batch_read
    from backend.tests.test_channel_engine import _plant_dataset

    def page(relation: str, *, after_ord: int, limit: int) -> list[dict[str, Any]]:
        del relation, after_ord, limit
        raise AssertionError("empty dataset has no page")

    _plant_dataset(monkeypatch, batch_read, row_count=0, page=page)

    class _Body:
        def run_round(self, step: Any, *, record: Any = None) -> dict[str, Any]:
            del step, record
            raise AssertionError("empty dataset has no round")

        def evaluate_round_template(
            self, path: str, schema: Mapping[str, Any]
        ) -> tuple[Any, NodeResult | None]:
            raise AssertionError(path)

    result = BATCH_READ.container.run(_batch_node(), FakeHooks(), _Body())
    assert result.status == "succeeded"
    assert result.ports == frozenset({"done"})
    assert result.output == {"count": 0, "total": 0, "batch_size": 1000}
    assert "iterations" not in result.output
