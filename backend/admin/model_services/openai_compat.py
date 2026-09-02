"""OpenAI-compatible embeddings POST (protocol openai_compat)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from backend.admin.model_services.errors import (
    ModelServiceTestFailed,
    ModelServiceUnavailable,
)

PROBE_TEXT = "refraq catalog search probe"
TIMEOUT_SEC = 30


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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        snippet = exc.read()[:300].decode("utf-8", errors="replace")
        raise ModelServiceTestFailed(
            f"Embeddings HTTP {exc.code} at {url}: {snippet}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
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


def probe_embeddings(*, url: str, model: str, api_key: str | None) -> tuple[int, str]:
    """Return (dimension, model) after a successful probe POST."""
    vectors = post_openai_embeddings(
        url=url, model=model, api_key=api_key, texts=[PROBE_TEXT]
    )
    return len(vectors[0]), model
