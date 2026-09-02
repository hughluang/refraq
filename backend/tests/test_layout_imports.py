"""Enforce backend layout published-API and dependency whitelist.

See docs/backend-layout.md §7–§8.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Package roots under backend/ (not tests, not alembic scripts as packages).
PACKAGE_DIRS = {
    "core": BACKEND_ROOT / "core",
    "admin": BACKEND_ROOT / "admin",
    "jobs": BACKEND_ROOT / "jobs",
    "metadata": BACKEND_ROOT / "metadata",
    "worker": BACKEND_ROOT / "worker",
}

# docs/backend-layout.md §3 published modules (prefix match after backend.).
PUBLISHED: dict[str, frozenset[str]] = {
    "admin": frozenset(
        {
            "admin.deps",
            "admin.permissions",
            "admin.errors",
            "admin.audit",
            "admin.roles",
            "admin.security",
            "admin.user_store",
            "admin.role_store",
            "admin.session_store",
            "admin.token_store",
            "admin.audit_store",
            "admin.system_parameters",
            "admin.parameters",
            "admin.federation",
            "admin.model_services",
            "admin.routers",
        }
    ),
    "jobs": frozenset(
        {
            "jobs.api",
            "jobs.parameters",
            "jobs.store",
            "jobs.errors",
            "jobs.schemas",
            "jobs.routers",
        }
    ),
    "metadata": frozenset(
        {
            "metadata.errors",
            "metadata.source_jobs",
            "metadata.catalog_embed_jobs",
            "metadata.source_schedules",
            "metadata.type_mappings.seeds",
            "metadata.mcp_catalog",
            "metadata.mcp_server",
            "metadata.mcp_http",
            "metadata.tasks",
            "metadata.routers",
        }
    ),
    "worker": frozenset(
        {
            "worker.parameters",
            "worker.api",
            "worker.due",
            "worker.errors",
            "worker.schemas",
            "worker.routers",
            "worker.schedules",
            "worker.app",
            "worker.tasks",
        }
    ),
}

# Temporary allowlist: (importer_module_prefix, imported_module_prefix).
# Keep empty unless a short-lived migration shim is unavoidable.
TEMPORARY_ALLOWLIST: frozenset[tuple[str, str]] = frozenset()


def _iter_py_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and "alembic" not in p.parts
    )


def _module_name(path: Path) -> str:
    rel = path.relative_to(BACKEND_ROOT)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imported_backend_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "backend" or node.module.startswith("backend."):
                found.add(node.module.removeprefix("backend.").rstrip("."))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "backend" or alias.name.startswith("backend."):
                    found.add(alias.name.removeprefix("backend.").rstrip("."))
    return found


def _owner_package(module: str) -> str | None:
    top = module.split(".", 1)[0]
    if top in PACKAGE_DIRS:
        return top
    return None


def _is_published_import(target_pkg: str, imported: str) -> bool:
    published = PUBLISHED.get(target_pkg, frozenset())
    for prefix in published:
        if imported == prefix or imported.startswith(prefix + "."):
            return True
    return False


def _allowlisted(importer: str, imported: str) -> bool:
    for imp_pref, tgt_pref in TEMPORARY_ALLOWLIST:
        if importer.startswith(imp_pref) and imported.startswith(tgt_pref):
            return True
    return False


@pytest.mark.parametrize("path", _iter_py_files(BACKEND_ROOT), ids=_module_name)
def test_layout_imports(path: Path) -> None:
    if path.is_relative_to(BACKEND_ROOT / "tests"):
        pytest.skip("tests may import anything")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    importer = _module_name(path)
    importer_pkg = _owner_package(importer)

    for imported in _imported_backend_modules(tree):
        if imported == "worker.app" or imported.startswith("worker.app."):
            if importer_pkg in {"admin", "jobs", "metadata", "core"} or importer.startswith(
                "routers."
            ):
                if not _allowlisted(importer, imported):
                    raise AssertionError(
                        f"{importer} must not import worker.app "
                        f"(use jobs.api / shared_task); imported {imported}"
                    )

        target_pkg = _owner_package(imported)
        if target_pkg is None or importer_pkg is None:
            continue
        if target_pkg == importer_pkg:
            continue

        # docs/backend-layout.md §8: admin may import core and own modules only.
        if importer_pkg == "admin" and target_pkg in {"jobs", "metadata", "worker"}:
            if not _allowlisted(importer, imported):
                raise AssertionError(
                    f"{importer} must not import {imported} "
                    "(admin may import core and own modules only)"
                )

        # docs/backend-layout.md §8 from-column: jobs may not import worker.
        if importer_pkg == "jobs" and target_pkg not in {"core", "admin"}:
            if not _allowlisted(importer, imported):
                raise AssertionError(
                    f"{importer} must not import {imported} "
                    "(jobs may import core and published admin only)"
                )

        # core must not import business packages (upgrade → published admin/worker/metadata seeds).
        if importer_pkg == "core":
            if target_pkg in {"admin", "jobs", "metadata", "worker"}:
                if importer == "core.upgrade" and target_pkg in {"admin", "worker", "metadata"}:
                    if target_pkg == "worker":
                        if imported == "worker.api" or imported.startswith("worker.api."):
                            continue
                        if imported == "worker.parameters" or imported.startswith(
                            "worker.parameters."
                        ):
                            continue
                    elif target_pkg == "metadata":
                        if _is_published_import("metadata", imported):
                            continue
                    elif _is_published_import("admin", imported):
                        continue
                if _allowlisted(importer, imported):
                    continue
                raise AssertionError(
                    f"core module {importer} must not import {imported}"
                )
            continue

        # Cross-package into another tiered package: published only.
        if target_pkg in PUBLISHED:
            if _is_published_import(target_pkg, imported):
                continue
            if _allowlisted(importer, imported):
                continue
            raise AssertionError(
                f"{importer} imports unpublished {imported} "
                f"(published prefixes for {target_pkg}: "
                f"{sorted(PUBLISHED[target_pkg])})"
            )


def test_no_top_level_repositories_package() -> None:
    assert not (BACKEND_ROOT / "repositories").exists()
