"""250,000 vs 1,000,000 RSS comparison. Default pytest does not collect this module."""

from __future__ import annotations

import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_NOTE = _ROOT / ".process" / "dataset-volume-acceptance.md"
_SIZES = (250_000, 1_000_000)
_PATHS = ("slow", "direct")
_LIMIT_BYTES = 50 * 1024 * 1024
_MIN_FREE_BYTES = 4 * 1024 * 1024 * 1024
_SOURCE_IDS = (
    "REFRAQ_TEST_PG_SOURCE_ID",
    "REFRAQ_TEST_ORACLE_SOURCE_ID",
    "REFRAQ_TEST_MSSQL_SOURCE_ID",
)


def _worker(path: str, rows: int) -> None:
    os.environ.setdefault("REFRAQ_STORE_BACKEND", "memory")
    os.environ.setdefault("CELERY_BROKER_URL", "memory://")
    os.environ.setdefault("REFRAQ_SECRETS_MASTER_KEY", "test-secrets-master-key")
    from backend.tests.test_dataset_volume_acceptance_pg import execute_path, volume_database

    with volume_database() as targets:
        item = execute_path(targets, path, rows)
    item["ru_maxrss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    sys.stdout.write(json.dumps(item) + "\n")


def _command(path: str, rows: int) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), "--worker", path, str(rows)]


def _retryable(text: str) -> bool:
    if "tuple concurrently updated" in text:
        return True
    return "password authentication failed" in text and "refraq_entity_owner" in text


def _run_worker(path: str, rows: int) -> dict:
    command = _command(path, rows)
    last_stdout = ""
    last_stderr = ""
    code = 1
    for attempt in (1, 2):
        print(f"manual start path={path} rows={rows} attempt={attempt}", flush=True)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            command,
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        last_stdout = proc.stdout or ""
        last_stderr = proc.stderr or ""
        code = proc.returncode
        if last_stderr:
            sys.stderr.write(last_stderr)
            sys.stderr.flush()
        if code == 0:
            line = last_stdout.strip().splitlines()[-1]
            return json.loads(line)
        if attempt == 1 and _retryable(last_stdout + last_stderr):
            time.sleep(3)
            continue
        break
    raise RuntimeError(
        "worker failed\ncommand: "
        + " ".join(command)
        + f"\nexit: {code}\nstdout:\n{last_stdout}\nstderr:\n{last_stderr}"
    )


def _external_lines() -> list[str]:
    missing = [name for name in _SOURCE_IDS if not os.environ.get(name)]
    present = [name for name in _SOURCE_IDS if os.environ.get(name)]
    lines = ["## External source", ""]
    if not present:
        lines.append(
            "No external Source run. Unset ids: " + ", ".join(missing) + "."
        )
    else:
        lines.append(
            "Present ids were not executed by this entry point: " + ", ".join(present) + "."
        )
        if missing:
            lines.append("Unset ids: " + ", ".join(missing) + ".")
    lines.append("")
    return lines


def _from_heading(text: str, heading: str) -> str:
    """Suffix that starts at ``heading``, or empty when that heading is absent."""
    marker = f"\n{heading}\n"
    index = text.find(marker)
    if index >= 0:
        return text[index + 1 :]
    if text.startswith(heading + "\n"):
        return text
    return ""


def _write_manual(body: str) -> None:
    existing = _NOTE.read_text(encoding="utf-8") if _NOTE.exists() else "# Dataset volume acceptance\n"
    issue = _from_heading(existing, "## Issue 09")
    kept = existing[: len(existing) - len(issue)] if issue else existing
    marker = "\n## Manual\n"
    if marker in kept:
        head = kept.split(marker, 1)[0]
    elif kept.startswith("## Manual\n"):
        head = "# Dataset volume acceptance\n"
    else:
        head = kept
    text = head.rstrip() + "\n\n" + body.rstrip() + "\n"
    if issue:
        text = text.rstrip() + "\n\n" + issue.strip("\n") + "\n"
    _NOTE.parent.mkdir(parents=True, exist_ok=True)
    _NOTE.write_text(text, encoding="utf-8")


def _blocked(reason: str) -> int:
    command = f"{sys.executable} {Path(__file__).resolve()}"
    body = "\n".join(
        [
            "## Manual",
            "",
            "Blocked. No 1,000,000-row numbers were measured.",
            "",
            reason,
            "",
            f"Command: `{command}`",
            "",
            *_external_lines(),
        ]
    )
    _write_manual(body)
    print(reason, flush=True)
    return 2


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[1] == "--worker":
        _worker(argv[2], int(argv[3]))
        return 0
    free = shutil.disk_usage("/").free
    if free < _MIN_FREE_BYTES:
        return _blocked(
            f"Free space on / is {free} bytes, under {_MIN_FREE_BYTES} bytes. "
            "That is not enough to hold two million-row entity tables."
        )
    results: dict[str, dict[int, dict]] = {}
    failures: list[str] = []
    try:
        for path in _PATHS:
            results[path] = {}
            for rows in _SIZES:
                item = _run_worker(path, rows)
                results[path][rows] = item
                print(
                    f"manual done path={path} rows={rows} "
                    f"ru_maxrss_bytes={item['ru_maxrss_bytes']} "
                    f"peak_rss_bytes={item['peak_rss_bytes']} "
                    f"durations_sec={item['durations_sec']}",
                    flush=True,
                )
            delta = abs(
                results[path][1_000_000]["ru_maxrss_bytes"]
                - results[path][250_000]["ru_maxrss_bytes"]
            )
            if delta >= _LIMIT_BYTES:
                failures.append(
                    f"{path} ru_maxrss differs by {delta} bytes "
                    f"(250000={results[path][250_000]['ru_maxrss_bytes']}, "
                    f"1000000={results[path][1_000_000]['ru_maxrss_bytes']})."
                )
                break
    except RuntimeError as exc:
        _write_manual(
            "\n".join(
                [
                    "## Manual",
                    "",
                    "Worker failed. Numbers below are only the runs that finished. "
                    "Missing sizes were not invented.",
                    "",
                    "```",
                    str(exc),
                    "```",
                    "",
                    *_result_lines(results),
                    *_external_lines(),
                ]
            )
        )
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    status = "failed" if failures else "passed"
    _write_manual(
        "\n".join(
            [
                "## Manual",
                "",
                f"Comparison {status}. Gate: absolute difference of process `ru_maxrss` "
                f"at 250,000 and 1,000,000 rows on the same path, limit {_LIMIT_BYTES} bytes. "
                "Durations are printed and not gated. Each size is its own process.",
                "",
                *_result_lines(results),
                *(["", *failures] if failures else []),
                "",
                *_external_lines(),
            ]
        )
    )
    if failures:
        print("\n".join(failures), file=sys.stderr, flush=True)
        return 1
    return 0


def _result_lines(results: dict[str, dict[int, dict]]) -> list[str]:
    lines = [
        "| path | rows | ru_maxrss bytes | sampled peak RSS bytes | durations (s) | row_count |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for path, sizes in results.items():
        for rows, item in sizes.items():
            lines.append(
                f"| {path} | {rows} | {item['ru_maxrss_bytes']} | {item['peak_rss_bytes']} | "
                f"{item['durations_sec']} | {item['row_count']} |"
            )
    return lines


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
