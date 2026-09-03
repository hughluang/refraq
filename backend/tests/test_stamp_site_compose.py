"""Site compose template and stamp invariants."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / ".github" / "scripts" / "stamp_site_compose.py"
TEMPLATE = REPO_ROOT / "deploy" / "compose.yaml"
ENV_EXAMPLE = REPO_ROOT / "deploy" / ".env.example"

sys.path.insert(0, str(SCRIPT.parent))
from stamp_site_compose import (  # noqa: E402
    EXPECTED_SENTINEL_COUNT,
    PRODUCT_IMAGE_RE,
    SENTINEL,
    stamp_compose,
    validate_version,
)


def test_template_is_not_a_live_site_pin() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "REFRAQ_VERSION" not in text
    assert "latest" not in PRODUCT_IMAGE_RE.findall(text)
    tags = PRODUCT_IMAGE_RE.findall(text)
    assert tags == [SENTINEL] * EXPECTED_SENTINEL_COUNT
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "REFRAQ_VERSION" not in env_text


@pytest.mark.parametrize("version", ["latest", "v0.1.3", SENTINEL, "", "1.2", "abc"])
def test_stamp_rejects_unusable_version(version: str) -> None:
    with pytest.raises(ValueError):
        validate_version(version)


def test_stamp_writes_one_version_on_all_product_images() -> None:
    stamped = stamp_compose(TEMPLATE.read_text(encoding="utf-8"), "1.2.3")
    assert SENTINEL not in stamped
    assert "REFRAQ_VERSION" not in stamped
    tags = PRODUCT_IMAGE_RE.findall(stamped)
    assert tags == ["1.2.3"] * EXPECTED_SENTINEL_COUNT
    assert "latest" not in tags


def test_stamp_cli_writes_output(tmp_path: Path) -> None:
    out = tmp_path / "docker-compose.yaml"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--version",
            "1.2.3",
            "--input",
            str(TEMPLATE),
            "--output",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    tags = PRODUCT_IMAGE_RE.findall(out.read_text(encoding="utf-8"))
    assert tags == ["1.2.3"] * EXPECTED_SENTINEL_COUNT


def test_stamped_compose_config_parses(tmp_path: Path) -> None:
    compose_bin = shutil.which("docker")
    if compose_bin is None:
        pytest.skip("docker is not installed")
    probe = subprocess.run(
        [compose_bin, "compose", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip(probe.stderr.strip() or "docker compose is not available")
    stamped = tmp_path / "docker-compose.yaml"
    stamped.write_text(
        stamp_compose(TEMPLATE.read_text(encoding="utf-8"), "1.2.3"),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "POSTGRES_PASSWORD": "test",
        "REFRAQ_SECRETS_MASTER_KEY": "test",
        "ADMIN_SESSION_SECRET": "test",
        "INITIAL_ADMIN_PASSWORD": "test",
    }
    result = subprocess.run(
        [compose_bin, "compose", "-f", str(stamped), "config"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
