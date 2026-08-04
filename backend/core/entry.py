"""Official product entry: Foundation Upgrade, then serve."""

from __future__ import annotations

import sys

from backend.core.config import get_settings
from backend.core.upgrade import migrate_with_advisory_lock, run_upgrade

# Re-export for callers/tests that imported migrate from entry.
__all__ = ["main", "migrate_with_advisory_lock", "run_upgrade"]


def main() -> None:
    settings = get_settings()
    if settings.store_backend != "persistent":
        print(
            "REFRAQ_STORE_BACKEND must be persistent for the official entrypoint",
            file=sys.stderr,
        )
        raise SystemExit(1)
    assert settings.database_url
    try:
        run_upgrade(settings.database_url)
    except Exception as exc:  # noqa: BLE001 — entry must exit non-zero with context
        print(f"upgrade failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.refraq_api_host,
        port=settings.refraq_api_port,
        factory=False,
    )


if __name__ == "__main__":
    main()
