"""Bound Dictionary code port. Composition injects the entity implementation."""

from __future__ import annotations

from typing import Protocol


class DictionaryCodesPort(Protocol):
    def active_codes(self, dictionary_id: str) -> frozenset[str] | None:
        """Active codes of the Dictionary, or None when it does not exist."""
        ...


_port: DictionaryCodesPort | None = None


def bind_dictionary_codes(port: DictionaryCodesPort | None) -> None:
    global _port
    _port = port


def dictionary_codes() -> DictionaryCodesPort:
    if _port is None:
        raise RuntimeError("dictionary codes port is not bound")
    return _port
