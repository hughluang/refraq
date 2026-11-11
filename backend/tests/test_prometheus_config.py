"""Scrape configuration and catalog retention wording."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMETHEUS = REPO_ROOT / "deploy" / "prometheus.yml"

HOST_METRICS = (
    "node_cpu_seconds_total",
    "node_procs_running",
    "node_memory_MemTotal_bytes",
    "node_memory_MemAvailable_bytes",
    "node_memory_SwapTotal_bytes",
    "node_memory_SwapFree_bytes",
    "node_filesystem_size_bytes",
    "node_filesystem_avail_bytes",
    "node_filesystem_files_free",
    "node_disk_io_time_seconds_total",
    "node_disk_io_time_weighted_seconds_total",
    "node_pressure_cpu_waiting_seconds_total",
    "node_pressure_cpu_stalled_seconds_total",
    "node_pressure_memory_waiting_seconds_total",
    "node_pressure_memory_stalled_seconds_total",
    "node_pressure_io_waiting_seconds_total",
    "node_pressure_io_stalled_seconds_total",
    "up",
)
POSTGRES_METRICS = (
    "pg_stat_database_numbackends",
    "pg_settings_max_connections",
    "pg_stat_activity_count",
    "pg_stat_checkpointer_num_timed_total",
    "pg_stat_checkpointer_num_requested_total",
    "pg_stat_checkpointer_write_time_total",
    "pg_stat_checkpointer_sync_time_total",
    "pg_stat_checkpointer_buffers_written_total",
    "pg_stat_database_temp_files",
    "pg_stat_database_temp_bytes",
    "up",
)
CONTAINER_METRICS = (
    "container_cpu_usage_seconds_total",
    "container_memory_working_set_bytes",
)
COMPOSE_SERVICES = (
    "postgres",
    "redis",
    "api",
    "worker",
    "beat",
    "mcp",
    "entity-mcp",
    "web",
)
# The catalog assertion looks for this token without putting CJK in the source.
FIFTEEN_DAYS_ZH = "15 \u5929"
RETENTION_TOKENS = ("15d", "15 days", FIFTEEN_DAYS_ZH, "1GB", "1073741824")


def _jobs(text: str) -> dict[str, str]:
    jobs: dict[str, str] = {}
    for part in text.split("\n  - job_name: ")[1:]:
        name, body = part.split("\n", 1)
        jobs[name] = body
    return jobs


def _keep_regex(body: str) -> str:
    match = re.search(r"(?m)^        regex: (.+)$", body)
    assert match is not None
    return match.group(1)


def test_prometheus_config_retains_fifteen_days_or_one_gibibyte() -> None:
    text = PROMETHEUS.read_text(encoding="utf-8")
    assert "scrape_interval: 30s" in text
    assert "scrape_timeout: 10s" in text
    assert (
        "storage:\n  tsdb:\n    retention:\n      time: 15d\n      size: 1073741824B\n"
        in text
    )
    assert "percentage:" not in text
    assert "--storage.tsdb.retention" not in text
    jobs = _jobs(text)
    assert list(jobs) == ["node_exporter", "postgres_exporter", "cadvisor"]
    assert 'targets: ["host.docker.internal:9100"]' in jobs["node_exporter"]
    assert 'targets: ["postgres-exporter:9187"]' in jobs["postgres_exporter"]
    assert 'targets: ["cadvisor:8080"]' in jobs["cadvisor"]
    assert "prometheus:9090" not in text
    assert _keep_regex(jobs["node_exporter"]) == "|".join(HOST_METRICS)
    assert _keep_regex(jobs["postgres_exporter"]) == "|".join(POSTGRES_METRICS)
    services = "|".join(COMPOSE_SERVICES)
    metrics = "|".join(CONTAINER_METRICS)
    assert _keep_regex(jobs["cadvisor"]) == (
        f"up;.*|({metrics});({services})"
    )
    assert "container_label_com_docker_compose_service" in jobs["cadvisor"]
    assert "ensure-entity-db" not in jobs["cadvisor"]


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        found: list[str] = []
        for item in value.values():
            found.extend(_strings(item))
        return found
    if isinstance(value, list):
        found = []
        for item in value:
            found.extend(_strings(item))
        return found
    return []


def _catalog_strings(data: dict[str, object]) -> list[str]:
    found: list[str] = []
    for key, value in data.items():
        if key == "host" or (isinstance(key, str) and key.startswith("host.")):
            found.extend(_strings(value))
        elif key == "problems.HOST_SERIES_UNAVAILABLE":
            found.extend(_strings(value))
        elif key == "problems" and isinstance(value, dict) and "HOST_SERIES_UNAVAILABLE" in value:
            found.extend(_strings(value["HOST_SERIES_UNAVAILABLE"]))
    return found


def test_locale_catalogs_do_not_name_retention() -> None:
    for catalog in (
        REPO_ROOT / "frontend" / "src" / "locales" / "en-US" / "common.json",
        REPO_ROOT / "frontend" / "src" / "locales" / "zh-CN" / "common.json",
    ):
        data = json.loads(catalog.read_text(encoding="utf-8"))
        for value in _catalog_strings(data):
            for token in RETENTION_TOKENS:
                assert token not in value
