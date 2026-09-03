#!/usr/bin/env python3
"""Replace the site compose sentinel with a release image tag.

Usage:
  python3 .github/scripts/stamp_site_compose.py --version 0.1.3 \\
    --input deploy/compose.yaml --output docker-compose.yaml
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

SENTINEL = "__REFRAQ_RELEASE_TAG__"
EXPECTED_SENTINEL_COUNT = 5
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
PRODUCT_IMAGE_RE = re.compile(
    r"ghcr\.io/hughluang/refraq-(?:api|web):(\S+)"
)


def validate_version(version: str) -> None:
    if version in {SENTINEL, "latest"} or version.startswith("v"):
        raise ValueError(
            f"version must be semver without a v prefix, not {version!r}"
        )
    if not VERSION_RE.fullmatch(version):
        raise ValueError(
            f"version must match X.Y.Z, not {version!r}"
        )


def stamp_compose(text: str, version: str) -> str:
    validate_version(version)
    if "REFRAQ_VERSION" in text:
        raise ValueError("template must not reference REFRAQ_VERSION")
    found = text.count(SENTINEL)
    if found != EXPECTED_SENTINEL_COUNT:
        raise ValueError(
            f"expected {EXPECTED_SENTINEL_COUNT} sentinel image tags, found {found}"
        )
    stamped = text.replace(SENTINEL, version)
    tags = PRODUCT_IMAGE_RE.findall(stamped)
    if len(tags) != EXPECTED_SENTINEL_COUNT:
        raise ValueError(
            f"expected {EXPECTED_SENTINEL_COUNT} product image tags, found {len(tags)}"
        )
    if any(tag != version for tag in tags):
        raise ValueError("stamped product image tags must all equal the version")
    if SENTINEL in stamped or "latest" in tags:
        raise ValueError("stamped compose still has a sentinel or latest tag")
    return stamped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="image tag without the v")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        stamped = stamp_compose(args.input.read_text(encoding="utf-8"), args.version)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    args.output.write_text(stamped, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
