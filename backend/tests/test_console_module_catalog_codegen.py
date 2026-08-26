"""Ensure frontend Console Module Identity artifacts match the backend seed."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEGEN_SCRIPT = REPO_ROOT / "scripts" / "gen_console_module_catalog.py"


def test_generated_console_module_catalog_is_current() -> None:
    result = subprocess.run(
        [sys.executable, str(CODEGEN_SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
