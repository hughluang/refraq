"""Ensure the Console Attribute Type catalog matches the backend module."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEGEN_SCRIPT = REPO_ROOT / "scripts" / "gen_attribute_types.py"


def test_generated_attribute_type_catalog_is_current() -> None:
    result = subprocess.run(
        [sys.executable, str(CODEGEN_SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
