"""Site compose template and stamp invariants."""

from __future__ import annotations

import os
import re
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
    PRODUCT_IMAGE_RE,
    SENTINEL,
    stamp_compose,
    validate_version,
)

PRODUCT_IMAGE_COUNT = 7


def test_template_restarts_beat_only() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    beat = text.split("\n  beat:\n", 1)[1].split("\n  mcp:\n", 1)[0]
    assert "restart: unless-stopped" in beat
    worker = text.split("\n  worker:\n", 1)[1].split("\n  beat:\n", 1)[0]
    assert "restart:" not in worker


def test_template_is_not_a_live_site_pin() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "REFRAQ_VERSION" not in text
    assert "latest" not in PRODUCT_IMAGE_RE.findall(text)
    tags = PRODUCT_IMAGE_RE.findall(text)
    assert tags == [SENTINEL] * PRODUCT_IMAGE_COUNT
    entity_mcp = text.split("\n  entity-mcp:\n", 1)[1].split("\n  web:\n", 1)[0]
    assert f"image: ghcr.io/hughluang/refraq-api:{SENTINEL}" in entity_mcp
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "REFRAQ_VERSION" not in env_text


def test_template_postgres_cluster_lives_on_named_volume() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    mounts = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("- refraq_pg:")
    ]
    assert mounts == ["- refraq_pg:/var/lib/postgresql"]
    assert "refraq_pg:/var/lib/postgresql/data" not in text
    assert "PGDATA:" not in text
    assert "entrypoint:" not in text
    assert ".refraq-copy-incomplete" not in text
    assert "ENTITY_OWNER_PASSWORD:?set ENTITY_OWNER_PASSWORD" in text
    assert "ENTITY_READER_PASSWORD:?set ENTITY_READER_PASSWORD" in text


def test_template_isolates_entity_database() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "5432/refraq_entity" in text
    assert "ensure-entity-db:" in text
    assert "service_completed_successfully" in text
    assert "backend.entity.bootstrap" in text
    assert "refraq:${POSTGRES_PASSWORD}@postgres:5432/refraq_entity" in text
    assert text.count("ENTITY_ADMIN_DATABASE_URL") == 1
    for line in text.splitlines():
        if "ENTITY_DATABASE_URL:" in line and "ENTITY_ADMIN" not in line:
            assert "refraq_entity_owner:" in line
        if "ENTITY_READER_DATABASE_URL:" in line:
            assert "refraq_reader:" in line


@pytest.mark.parametrize("version", ["latest", "v0.1.3", SENTINEL, "", "1.2", "abc"])
def test_stamp_rejects_unusable_version(version: str) -> None:
    with pytest.raises(ValueError):
        validate_version(version)


def test_stamp_writes_one_version_on_all_product_images() -> None:
    stamped = stamp_compose(TEMPLATE.read_text(encoding="utf-8"), "1.2.3")
    assert SENTINEL not in stamped
    assert "REFRAQ_VERSION" not in stamped
    tags = PRODUCT_IMAGE_RE.findall(stamped)
    assert tags == ["1.2.3"] * PRODUCT_IMAGE_COUNT
    assert "latest" not in tags


def test_stamp_rejects_template_with_any_other_sentinel_count() -> None:
    image = f"    image: ghcr.io/hughluang/refraq-api:{SENTINEL}\n"
    for count in (6, 8):
        with pytest.raises(ValueError, match="expected 7 sentinel image tags"):
            stamp_compose(image * count, "1.2.3")


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
    assert tags == ["1.2.3"] * PRODUCT_IMAGE_COUNT


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
        "ENTITY_OWNER_PASSWORD": "test",
        "ENTITY_READER_PASSWORD": "test",
        "ENTITY_SIGNER_PASSWORD": "test",
        "REFRAQ_MONITOR_PASSWORD": "test",
        "REFRAQ_SECRETS_MASTER_KEY": "test",
        "ADMIN_SESSION_SECRET": "test",
        "INITIAL_ADMIN_PASSWORD": "test",
    }
    scrape = REPO_ROOT / "deploy" / "prometheus.yml"
    (tmp_path / "prometheus.yml").write_text(
        scrape.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = subprocess.run(
        [compose_bin, "compose", "-f", str(stamped), "config"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _service_block(text: str, name: str) -> str:
    lines = text.splitlines(keepends=True)
    header = f"  {name}:\n"
    start = None
    for index, line in enumerate(lines):
        if line == header:
            start = index + 1
            break
    assert start is not None, name
    end = start
    while end < len(lines):
        line = lines[end]
        if line == "volumes:\n" or (
            line.startswith("  ")
            and not line.startswith("   ")
            and line.endswith(":\n")
        ):
            break
        end += 1
    return "".join(lines[start:end])


def test_site_compose_runs_node_exporter_on_the_host() -> None:
    block = _service_block(TEMPLATE.read_text(encoding="utf-8"), "node-exporter")
    assert "image: quay.io/prometheus/node-exporter:v1.12.1" in block
    assert "__REFRAQ_RELEASE_TAG__" not in block
    assert "network_mode: host" in block
    assert "pid: host" in block
    assert "target: /host" in block
    assert "read_only: true" in block
    assert "propagation: rslave" in block
    assert "--path.rootfs=/host" in block
    assert "--collector.disable-defaults" in block
    assert re.findall(r"(?m)^\s+- --collector\.([a-z0-9_]+)\s*$", block) == [
        "cpu",
        "meminfo",
        "filesystem",
        "diskstats",
        "pressure",
        "stat",
    ]
    assert "ports:" not in block


# cAdvisor 0.60.6 default --disable_metrics (cmd/cadvisor.go ignoreMetrics)
# union the families this screen does not chart. cpu and memory stay on.
CADVISOR_DISABLED_METRICS = ",".join(
    [
        "advtcp",
        "app",
        "cpuLoad",
        "cpu_topology",
        "cpuset",
        "disk",
        "diskIO",
        "hugetlb",
        "memory_numa",
        "network",
        "oom_event",
        "percpu",
        "perf_event",
        "process",
        "referenced_memory",
        "resctrl",
        "sched",
        "tcp",
        "udp",
    ]
)


def test_site_compose_runs_cadvisor_without_a_published_port() -> None:
    block = _service_block(TEMPLATE.read_text(encoding="utf-8"), "cadvisor")
    assert "image: ghcr.io/google/cadvisor:v0.60.6" in block
    assert "__REFRAQ_RELEASE_TAG__" not in block
    assert "ports:" not in block
    assert "--docker_only" in block
    assert "--housekeeping_interval=15s" in block
    assert "--store_container_labels=false" in block
    assert "--whitelisted_container_labels=com.docker.compose.service" in block
    match = re.search(r"--disable_metrics=(\S+)", block)
    assert match is not None
    disabled = set(match.group(1).split(","))
    assert disabled == set(CADVISOR_DISABLED_METRICS.split(","))
    assert "cpu" not in disabled
    assert "memory" not in disabled
    assert "privileged: true" in block
    assert "/:/rootfs:ro" in block
    assert "/var/run:/var/run:ro" in block
    assert "/sys:/sys:ro" in block
    assert "/var/lib/docker/:/var/lib/docker:ro" in block
    assert "/dev/disk/:/dev/disk:ro" in block
    assert "/dev/kmsg" in block


def test_site_compose_creates_monitor_role_again() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    block = _service_block(text, "ensure-monitor-role")
    assert "image: pgvector/pgvector:pg18" in block
    assert 'restart: "no"' in block
    assert "command:" in block
    assert "entrypoint:" not in block
    assert "condition: service_healthy" in block
    assert "--host=postgres" in block
    assert "--username=refraq" in block
    assert "--dbname=refraq" in block
    assert "CREATE ROLE refraq_monitor" in block
    assert "ALTER ROLE refraq_monitor" in block
    assert "LOGIN" in block
    assert "NOSUPERUSER" in block
    assert "NOT EXISTS" in block
    assert "GRANT pg_monitor TO refraq_monitor" in block
    assert "${REFRAQ_MONITOR_PASSWORD:?set REFRAQ_MONITOR_PASSWORD}" in block
    between_worker_and_beat = text.split("\n  worker:\n", 1)[1].split("\n  beat:\n", 1)[0]
    assert "ensure-monitor-role" not in between_worker_and_beat
    bootstrap = (REPO_ROOT / "backend" / "entity" / "bootstrap.py").read_text(encoding="utf-8")
    assert "refraq_monitor" not in bootstrap


# Names registerCollector registers in postgres_exporter v0.20.1,
# except the four collectors this screen enables.
POSTGRES_EXPORTER_ENABLED = [
    "settings",
    "stat_database",
    "stat_activity",
    "stat_checkpointer",
]
POSTGRES_EXPORTER_DISABLED = [
    "buffercache_summary",
    "database",
    "database_wraparound",
    "locks",
    "long_running_transactions",
    "postmaster",
    "process_idle",
    "replication",
    "replication_slots",
    "roles",
    "stat_activity_autovacuum",
    "stat_archiver",
    "stat_bgwriter",
    "stat_progress_vacuum",
    "stat_replication",
    "stat_statements",
    "stat_user_tables",
    "stat_wal_receiver",
    "statio_user_indexes",
    "statio_user_tables",
    "wal",
    "xlog_location",
]


def test_site_compose_postgres_exporter_logs_in_as_monitor() -> None:
    block = _service_block(TEMPLATE.read_text(encoding="utf-8"), "postgres-exporter")
    assert "image: quay.io/prometheuscommunity/postgres-exporter:v0.20.1" in block
    assert "__REFRAQ_RELEASE_TAG__" not in block
    assert "ports:" not in block
    assert "PG_EXPORTER_COLLECTION_TIMEOUT" in block and "8s" in block
    assert (
        "postgresql://refraq_monitor:${REFRAQ_MONITOR_PASSWORD:?set REFRAQ_MONITOR_PASSWORD}@postgres:5432/refraq"
        in block
    )
    assert "--collector.disable-defaults" not in block
    assert "--disable-default-metrics" not in block
    assert "ensure-monitor-role:" in block
    assert "condition: service_completed_successfully" in block
    enabled = re.findall(r"(?m)^\s+- --collector\.([a-z0-9_]+)\s*$", block)
    disabled = re.findall(r"(?m)^\s+- --no-collector\.([a-z0-9_]+)\s*$", block)
    assert enabled == POSTGRES_EXPORTER_ENABLED
    assert disabled == POSTGRES_EXPORTER_DISABLED
    assert "stat_checkpointer" in enabled
    for name in ("database", "stat_user_tables", "statio_user_tables", "stat_bgwriter"):
        assert name in disabled


def test_site_compose_runs_prometheus_below_postgres_io_weight() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    block = _service_block(text, "prometheus")
    postgres = _service_block(text, "postgres")
    assert "image: quay.io/prometheus/prometheus:v3.15.1" in block
    assert "__REFRAQ_RELEASE_TAG__" not in block
    assert "ports:" not in block
    assert re.findall(r"(?m)^\s+- (--\S+)\s*$", block) == [
        "--storage.tsdb.path=/prometheus",
        "--config.file=/etc/prometheus/prometheus.yml",
    ]
    assert "--storage.tsdb.retention" not in text
    assert "./prometheus.yml:/etc/prometheus/prometheus.yml:ro" in block
    assert "refraq_prometheus:/prometheus" in block
    assert "host.docker.internal:host-gateway" in block
    assert "weight: 100" in block
    assert "weight: 500" in postgres
    assert "refraq_prometheus:" in text.split("\nvolumes:\n", 1)[1]


def test_local_compose_has_no_collectors_or_series_store() -> None:
    text = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")
    for name in (
        "node-exporter",
        "cadvisor",
        "postgres-exporter",
        "prometheus",
        "ensure-monitor-role",
        "refraq_prometheus",
        "prometheus.yml",
    ):
        assert name not in text
