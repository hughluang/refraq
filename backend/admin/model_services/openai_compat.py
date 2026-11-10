"""OpenAI-compatible embeddings POST (protocol openai_compat)."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

from backend.admin.model_services.errors import (
    ModelServiceTestFailed,
    ModelServiceTimeout,
    ModelServiceUnavailable,
)

PROBE_TEXT = "refraq catalog search probe"
TIMEOUT_SEC = 30
TIMEOUT_SEC_MIN = 15
TIMEOUT_SEC_MAX = 300
EMBEDDING_OUTPUT_DIM = 1024


def post_openai_embeddings(
    *,
    url: str,
    model: str,
    api_key: str | None,
    texts: list[str],
    timeout: int = TIMEOUT_SEC,
) -> list[list[float]]:
    if not texts:
        return []
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    deadline = f"Embeddings request timed out after {timeout}s calling {url}"
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        code = exc.code
        exc.close()
        raise ModelServiceTestFailed(f"Embeddings HTTP {code} at {url}") from None
    except TimeoutError as exc:
        raise ModelServiceTimeout(deadline) from exc
    except json.JSONDecodeError:
        raise ModelServiceTestFailed(
            f"Unusable embeddings response from {url}"
        ) from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ModelServiceTimeout(deadline) from exc
        raise ModelServiceUnavailable(f"Cannot reach embeddings URL {url}") from exc
    except OSError as exc:
        raise ModelServiceUnavailable(f"Cannot reach embeddings URL {url}") from exc
    return _ordered_vectors(body, expected=len(texts), url=url)


def _unusable(url: str) -> ModelServiceTestFailed:
    return ModelServiceTestFailed(f"Unusable embeddings response from {url}")


def _ordered_vectors(body: object, *, expected: int, url: str) -> list[list[float]]:
    """Restore input order. Invalid provider rows fail the call."""
    if not isinstance(body, dict):
        raise _unusable(url)
    rows = body.get("data")
    if not isinstance(rows, list) or len(rows) != expected:
        raise _unusable(url)
    by_index: dict[int, list[float]] = {}
    width: int | None = None
    for row in rows:
        if not isinstance(row, dict) or "index" not in row or "embedding" not in row:
            raise _unusable(url)
        index = row["index"]
        if isinstance(index, bool) or not isinstance(index, int):
            raise _unusable(url)
        embedding = row["embedding"]
        if not isinstance(embedding, list) or not embedding:
            raise _unusable(url)
        vector: list[float] = []
        for item in embedding:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise _unusable(url)
            try:
                number = float(item)
            except OverflowError:
                raise _unusable(url) from None
            if not math.isfinite(number):
                raise _unusable(url)
            vector.append(number)
        if width is None:
            width = len(vector)
        elif len(vector) != width:
            raise _unusable(url)
        by_index[index] = vector
    if any(i not in by_index for i in range(expected)):
        raise _unusable(url)
    return [by_index[i] for i in range(expected)]


def probe_embeddings(
    *, url: str, model: str, api_key: str | None, timeout: int = TIMEOUT_SEC
) -> tuple[int, str]:
    """Return (dimension, model) after a successful probe POST."""
    vectors = post_openai_embeddings(
        url=url,
        model=model,
        api_key=api_key,
        texts=[PROBE_TEXT],
        timeout=timeout,
    )
    return len(vectors[0]), model
