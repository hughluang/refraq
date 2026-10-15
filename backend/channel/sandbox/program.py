"""Author code is the body of ``def main(self)``. Compilation does not execute it."""

from __future__ import annotations

CODE_MAX_BYTES = 64 * 1024


def function_source(source: str) -> str:
    """Indent ``source`` as the body of ``def main(self)``."""
    lines = source.splitlines()
    if not lines:
        lines = [""]
    body = "\n".join("" if not line.strip() else f"    {line}" for line in lines)
    return f"def main(self):\n{body}\n"


def author_line(lineno: int | None) -> int:
    """Map a line in the wrapped function back to the author's source."""
    if lineno is None or lineno <= 1:
        return 1
    return lineno - 1
