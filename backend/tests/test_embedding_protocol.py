"""Published embedding call: protocol, projection, and safe failures."""

from __future__ import annotations

import json

import pytest
from backend.admin.model_services.records import ModelServiceRecord, PurposeState
from backend.admin.model_services.store import get_model_service_store
from backend.core.time import utc_now

_URL = "http://embed.test/v1/embeddings"
_SECRET = "sk-test-credential"


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_Body":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _seed(
    *,
    generation: int = 3,
    ready: bool = False,
    closed: bool = False,
    url: str = _URL,
    secret: str | None = _SECRET,
    timeout_sec: int = 45,
    model: str = "qwen-test",
    service_id: str = "msvc_test",
) -> None:
    now = utc_now()
    store = get_model_service_store()
    store.save(
        ModelServiceRecord(
            id=service_id,
            purpose="embedding",
            protocol="openai_compat",
            display_name="test",
            url=url,
            model=model,
            timeout_sec=timeout_sec,
            secret=secret,
            created_at=now,
            updated_at=now,
        )
    )
    store.save_purpose(
        PurposeState(
            purpose="embedding",
            in_use_id=service_id,
            closed=closed,
            ready=ready,
            generation=generation,
        )
    )


def _json_body(rows: list[dict[str, object]]) -> _Body:
    return _Body(json.dumps({"data": rows}).encode("utf-8"))


def test_published_call_returns_ordered_vectors_and_space_without_credentials(
    monkeypatch,
) -> None:
    from backend.admin.model_services import embed_texts, openai_compat

    _seed()
    captured: dict[str, object] = {}

    def _urlopen(req: object, timeout: int = 0) -> _Body:
        captured["timeout"] = timeout
        captured["payload"] = json.loads(req.data.decode("utf-8"))  # type: ignore[attr-defined]
        captured["authorization"] = req.get_header("Authorization")  # type: ignore[attr-defined]
        return _json_body(
            [
                {"index": 2, "embedding": [0.5, 0.5]},
                {"index": 0, "embedding": [0.1, 0.2]},
                {"index": 1, "embedding": [0.3, 0.4]},
            ]
        )

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    result = embed_texts(["alpha", "beta", "gamma"], expected_generation=3)
    assert result.vectors == [[0.1, 0.2], [0.3, 0.4], [0.5, 0.5]]
    assert result.space.service_id == "msvc_test"
    assert result.space.generation == 3
    assert result.space.processing_contract == "prefix-1024-l2-v1"
    assert captured["payload"] == {
        "model": "qwen-test",
        "input": ["alpha", "beta", "gamma"],
    }
    assert captured["authorization"] == "Bearer sk-test-credential"
    assert captured["timeout"] == 45
    rendered = repr(result)
    assert "sk-test-credential" not in rendered
    assert "alpha" not in rendered
    purpose = get_model_service_store().get_purpose("embedding")
    assert purpose.generation == 3
    assert purpose.ready is False


def test_empty_input_returns_no_vectors_and_does_not_connect(monkeypatch) -> None:
    from backend.admin.model_services import embed_texts, openai_compat

    _seed(generation=4, service_id="msvc_empty")

    def _urlopen(_req: object, timeout: int = 0) -> _Body:
        raise AssertionError("connection opened")

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    result = embed_texts([], expected_generation=4)
    assert result.vectors == []
    assert result.space.service_id == "msvc_empty"
    assert result.space.generation == 4
    assert result.space.processing_contract == "prefix-1024-l2-v1"
    assert _SECRET not in repr(result)


def test_closed_service_refuses_before_connect(monkeypatch) -> None:
    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import ModelServiceClosed

    _seed(closed=True)
    calls = {"n": 0}

    def _urlopen(_req: object, timeout: int = 0) -> _Body:
        calls["n"] += 1
        return _json_body([{"index": 0, "embedding": [0.1, 0.2]}])

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    with pytest.raises(ModelServiceClosed) as exc_info:
        embed_texts(["classified-phrase"], expected_generation=3)
    assert calls["n"] == 0
    message = str(exc_info.value)
    assert "classified-phrase" not in message
    assert _SECRET not in message


def test_generation_mismatch_refuses_before_connect(monkeypatch) -> None:
    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import ModelServiceGenerationMismatch

    _seed(generation=3)
    calls = {"n": 0}

    def _urlopen(_req: object, timeout: int = 0) -> _Body:
        calls["n"] += 1
        return _json_body([{"index": 0, "embedding": [0.1, 0.2]}])

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    with pytest.raises(ModelServiceGenerationMismatch) as exc_info:
        embed_texts(["classified-phrase"], expected_generation=2)
    assert calls["n"] == 0
    message = str(exc_info.value)
    assert "classified-phrase" not in message
    assert _SECRET not in message
    assert get_model_service_store().get_purpose("embedding").generation == 3


def test_missing_url_refuses_before_connect(monkeypatch) -> None:
    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import ModelServiceEndpointMissing

    _seed(url="")
    calls = {"n": 0}

    def _urlopen(_req: object, timeout: int = 0) -> _Body:
        calls["n"] += 1
        return _json_body([{"index": 0, "embedding": [0.1, 0.2]}])

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    with pytest.raises(ModelServiceEndpointMissing) as exc_info:
        embed_texts(["classified-phrase"], expected_generation=3)
    assert calls["n"] == 0
    message = str(exc_info.value)
    assert "classified-phrase" not in message
    assert _SECRET not in message


def test_no_in_use_service_refuses_before_connect(monkeypatch) -> None:
    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import ModelServiceNotInUse

    calls = {"n": 0}

    def _urlopen(_req: object, timeout: int = 0) -> _Body:
        calls["n"] += 1
        return _json_body([{"index": 0, "embedding": [0.1, 0.2]}])

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    with pytest.raises(ModelServiceNotInUse) as exc_info:
        embed_texts(["classified-phrase"], expected_generation=0)
    assert calls["n"] == 0
    message = str(exc_info.value)
    assert "classified-phrase" not in message
    assert _SECRET not in message


def test_inputs_above_32_are_split_and_returned_in_input_order(monkeypatch) -> None:
    from backend.admin.model_services import embed_texts, openai_compat

    _seed(secret=None)
    seen: list[list[str]] = []

    def _urlopen(req: object, timeout: int = 0) -> _Body:
        payload = json.loads(req.data.decode("utf-8"))  # type: ignore[attr-defined]
        assert set(payload) == {"model", "input"}
        chunk = list(payload["input"])
        seen.append(chunk)
        rows = [
            {"index": index, "embedding": [float(index), 1.0]}
            for index in range(len(chunk))
        ]
        rows.reverse()
        return _json_body(rows)

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    texts = [f"item-{index:02d}" for index in range(40)]
    result = embed_texts(texts, expected_generation=3)
    assert [len(chunk) for chunk in seen] == [32, 8]
    assert seen[0] == texts[:32]
    assert seen[1] == texts[32:]
    assert result.vectors[0] == [0.0, 1.0]
    assert result.vectors[31] == [31.0, 1.0]
    assert result.vectors[32] == [0.0, 1.0]
    assert result.vectors[39] == [7.0, 1.0]
    assert len(result.vectors) == 40


def test_failed_batch_fails_the_call_without_retry_or_partial_vectors(
    monkeypatch,
) -> None:
    import io
    import urllib.error

    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import ModelServiceTestFailed

    _seed()
    calls = {"n": 0}

    def _urlopen(req: object, timeout: int = 0) -> _Body:
        calls["n"] += 1
        if calls["n"] == 1:
            payload = json.loads(req.data.decode("utf-8"))  # type: ignore[attr-defined]
            rows = [
                {"index": index, "embedding": [0.1, 0.2]}
                for index in range(len(payload["input"]))
            ]
            return _json_body(rows)
        raise urllib.error.HTTPError(
            _URL,
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(b"provider-secret-blob classified-phrase sk-test-credential"),
        )

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    texts = [f"item-{index:02d}" for index in range(33)]
    with pytest.raises(ModelServiceTestFailed) as exc_info:
        embed_texts(texts, expected_generation=3)
    assert calls["n"] == 2
    message = str(exc_info.value)
    assert "classified-phrase" not in message
    assert "provider-secret-blob" not in message
    assert _SECRET not in message


def test_mixed_widths_across_batches_fail_the_call(monkeypatch) -> None:
    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import ModelServiceTestFailed

    _seed()
    calls = {"n": 0}

    def _urlopen(req: object, timeout: int = 0) -> _Body:
        calls["n"] += 1
        payload = json.loads(req.data.decode("utf-8"))  # type: ignore[attr-defined]
        width = 2 if calls["n"] == 1 else 3
        rows = [
            {"index": index, "embedding": [0.1] * width}
            for index in range(len(payload["input"]))
        ]
        return _json_body(rows)

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    texts = [f"classified-phrase-{index:02d}" for index in range(33)]
    with pytest.raises(ModelServiceTestFailed) as exc_info:
        embed_texts(texts, expected_generation=3)
    assert calls["n"] == 2
    message = str(exc_info.value)
    assert "classified-phrase" not in message
    assert _SECRET not in message


@pytest.mark.parametrize(
    ("texts", "raw"),
    [
        (["classified-phrase"], b'{"data":[{"index":1,"embedding":[0.1,0.2]}]}'),
        (
            ["classified-phrase", "other-phrase"],
            b'{"data":[{"index":0,"embedding":[9.0,9.0]},{"index":0,"embedding":[0.1,0.2]}]}',
        ),
        (["classified-phrase"], b'{"data":[{"index":"0","embedding":[0.1,0.2]}]}'),
        (
            ["classified-phrase"],
            b'{"data":[{"index":0,"embedding":[0.1,0.2]},{"index":1,"embedding":[0.3,0.4]}]}',
        ),
        (["classified-phrase"], b'{"data":[{"index":0,"embedding":[]}]}'),
        (["classified-phrase"], b'{"data":[{"index":0,"embedding":[1e309]}]}'),
        (["classified-phrase"], b'{"data":[{"index":0,"embedding":[true,0.2]}]}'),
        (["classified-phrase"], b'{"data":[{"index":0,"embedding":["0.2",0.2]}]}'),
        (
            ["classified-phrase", "other-phrase"],
            b'{"data":[{"index":0,"embedding":[0.1,0.2]},{"index":1,"embedding":[0.3]}]}',
        ),
    ],
    ids=[
        "missing-index",
        "duplicate-index",
        "non-integer-index",
        "count-mismatch",
        "empty-vector",
        "non-finite",
        "bool-element",
        "non-numeric-element",
        "mixed-dimensions",
    ],
)
def test_malformed_provider_output_fails_the_call(
    monkeypatch, texts: list[str], raw: bytes
) -> None:
    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import ModelServiceTestFailed

    _seed()

    def _urlopen(_req: object, timeout: int = 0) -> _Body:
        return _Body(raw)

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    with pytest.raises(ModelServiceTestFailed) as exc_info:
        embed_texts(texts, expected_generation=3)
    message = str(exc_info.value)
    assert "classified-phrase" not in message
    assert "other-phrase" not in message
    assert _SECRET not in message


def test_projection_matches_prefix_1024_l2_rule(monkeypatch) -> None:
    from backend.admin.model_services import embed_texts, openai_compat

    _seed(generation=7)
    native_holder: dict[str, list[float]] = {}

    def _urlopen(_req: object, timeout: int = 0) -> _Body:
        native = native_holder["vector"]
        return _json_body([{"index": 0, "embedding": native}])

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)

    native_holder["vector"] = [3.0, 4.0, 9.0]
    short = embed_texts(["q"], expected_generation=7)
    assert short.vectors == [[3.0, 4.0, 9.0]]

    native_holder["vector"] = [3.0, 4.0] + [0.0] * 1022
    exact = embed_texts(["q"], expected_generation=7)
    assert exact.vectors == [[3.0, 4.0] + [0.0] * 1022]

    native_holder["vector"] = [3.0, 4.0] + [0.0] * 1022 + [9.0]
    long = embed_texts(["q"], expected_generation=7)
    assert long.vectors == [[0.6, 0.8] + [0.0] * 1022]
    assert long.space.processing_contract == "prefix-1024-l2-v1"
    assert long.space.generation == 7
    assert long.space.service_id == "msvc_test"

    native_holder["vector"] = [0.0] * 1024 + [5.0]
    zero_norm = embed_texts(["q"], expected_generation=7)
    assert zero_norm.vectors == [[0.0] * 1024]
    assert get_model_service_store().get_purpose("embedding").generation == 7


def test_generation_change_during_request_discards_provider_result(
    monkeypatch,
) -> None:
    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import ModelServiceGenerationMismatch
    from backend.admin.model_services.records import PurposeState

    _seed(generation=3)

    def _urlopen(_req: object, timeout: int = 0) -> _Body:
        store = get_model_service_store()
        state = store.get_purpose("embedding")
        store.save_purpose(
            PurposeState(
                purpose=state.purpose,
                in_use_id=state.in_use_id,
                closed=state.closed,
                ready=state.ready,
                generation=state.generation + 1,
            )
        )
        return _json_body([{"index": 0, "embedding": [0.1, 0.2]}])

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    with pytest.raises(ModelServiceGenerationMismatch) as exc_info:
        embed_texts(["classified-phrase"], expected_generation=3)
    message = str(exc_info.value)
    assert "classified-phrase" not in message
    assert _SECRET not in message
    assert "[0.1" not in message
    assert get_model_service_store().get_purpose("embedding").generation == 4


def test_timeout_and_unreachable_name_the_url_without_submitted_text(
    monkeypatch,
) -> None:
    import urllib.error

    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import (
        ModelServiceTimeout,
        ModelServiceUnavailable,
    )

    _seed(timeout_sec=30)

    def _timeout(_req: object, timeout: int = 0) -> _Body:
        raise TimeoutError("timed out")

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _timeout)
    with pytest.raises(ModelServiceTimeout) as timed_out:
        embed_texts(["classified-phrase"], expected_generation=3)
    timeout_message = str(timed_out.value)
    assert _URL in timeout_message
    assert "30s" in timeout_message
    assert "classified-phrase" not in timeout_message
    assert _SECRET not in timeout_message

    def _refuse(_req: object, timeout: int = 0) -> _Body:
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _refuse)
    with pytest.raises(ModelServiceUnavailable) as refused:
        embed_texts(["classified-phrase"], expected_generation=3)
    assert not isinstance(refused.value, ModelServiceTimeout)
    refused_message = str(refused.value)
    assert _URL in refused_message
    assert "classified-phrase" not in refused_message
    assert _SECRET not in refused_message


def test_unreadable_provider_document_is_omitted(monkeypatch) -> None:
    from backend.admin.model_services import embed_texts, openai_compat
    from backend.admin.model_services.errors import ModelServiceTestFailed

    _seed()
    raw = b"classified-phrase provider-secret-blob sk-test-credential"

    def _urlopen(_req: object, timeout: int = 0) -> _Body:
        return _Body(raw)

    monkeypatch.setattr(openai_compat.urllib.request, "urlopen", _urlopen)
    with pytest.raises(ModelServiceTestFailed) as exc_info:
        embed_texts(["classified-phrase"], expected_generation=3)
    message = str(exc_info.value)
    assert "classified-phrase" not in message
    assert "provider-secret-blob" not in message
    assert _SECRET not in message
    assert _URL in message
