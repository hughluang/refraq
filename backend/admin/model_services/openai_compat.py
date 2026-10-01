"""OpenAI-compatible embeddings POST (protocol openai_compat)."""

from __future__ import annotations

import json
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
        snippet = exc.read()[:300].decode("utf-8", errors="replace")
        raise ModelServiceTestFailed(
            f"Embeddings HTTP {exc.code} at {url}: {snippet}"
        ) from exc
    except TimeoutError as exc:
        raise ModelServiceTimeout(deadline) from exc
    except json.JSONDecodeError as exc:
        raise ModelServiceTestFailed(
            f"Unusable embeddings response from {url}"
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise ModelServiceTimeout(deadline) from exc
        raise ModelServiceUnavailable(f"Cannot reach embeddings URL {url}") from exc
    except OSError as exc:
        raise ModelServiceUnavailable(f"Cannot reach embeddings URL {url}") from exc
    rows = body.get("data") or []
    try:
        by_index = {int(row["index"]): row["embedding"] for row in rows}
        vectors = [list(by_index[i]) for i in range(len(texts))]
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelServiceTestFailed(
            f"Unusable embeddings response from {url}"
        ) from exc
    if any(not vec or not all(isinstance(n, (int, float)) for n in vec) for vec in vectors):
        raise ModelServiceTestFailed(f"Unusable embeddings response from {url}")
    return vectors


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
