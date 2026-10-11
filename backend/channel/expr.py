"""Literal versus {{ }} expression fields."""

from __future__ import annotations


def expression_body(value: str) -> str | None:
    text = value.strip()
    if text.startswith("{{") and text.endswith("}}"):
        return text[2:-2].strip()
    return None
