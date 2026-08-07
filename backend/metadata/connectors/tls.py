"""Shared TLS / connect_args helpers for SQLAlchemy connectors."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from typing import Iterator

from backend.metadata.connectors.base import SourceEndpoint


@contextmanager
def tls_temp_files(endpoint: SourceEndpoint) -> Iterator[dict[str, str]]:
    """Write PEM blobs to temp files; yield path map for driver connect_args."""
    paths: dict[str, str] = {}
    handles: list[tempfile._TemporaryFileWrapper[str]] = []
    try:
        if endpoint.ssl_root_cert:
            fh = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
            fh.write(endpoint.ssl_root_cert)
            fh.flush()
            handles.append(fh)
            paths["sslrootcert"] = fh.name
        if endpoint.ssl_client_cert:
            fh = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
            fh.write(endpoint.ssl_client_cert)
            fh.flush()
            handles.append(fh)
            paths["sslcert"] = fh.name
        if endpoint.ssl_client_key:
            fh = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
            fh.write(endpoint.ssl_client_key)
            fh.flush()
            handles.append(fh)
            paths["sslkey"] = fh.name
        yield paths
    finally:
        for fh in handles:
            try:
                fh.close()
            except OSError:
                pass
            try:
                os.unlink(fh.name)
            except OSError:
                pass


def postgres_connect_args(endpoint: SourceEndpoint, paths: dict[str, str]) -> dict:
    args: dict = {}
    mode = endpoint.ssl_mode or "require"
    if mode != "disable":
        args["sslmode"] = mode
        if "sslrootcert" in paths:
            args["sslrootcert"] = paths["sslrootcert"]
        if "sslcert" in paths:
            args["sslcert"] = paths["sslcert"]
        if "sslkey" in paths:
            args["sslkey"] = paths["sslkey"]
    else:
        args["sslmode"] = "disable"
    # Whitelist a few safe extras
    for key in ("application_name", "options"):
        if key in endpoint.extra:
            args[key] = endpoint.extra[key]
    return args
