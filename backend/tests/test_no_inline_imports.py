"""Enforce top-level imports in production backend code.

See docs/backend-layout.md § Import placement and ADR 0020.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# (module_name without backend. prefix, imported top-level name) — optional process entry only.
INLINE_IMPORT_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("core.entry", "uvicorn"),
    }
)


def _iter_prod_py_files() -> list[Path]:
    return sorted(
        p
        for p in BACKEND_ROOT.rglob("*.py")
        if "__pycache__" not in p.parts
        and "alembic" not in p.parts
        and "tests" not in p.parts
    )


def _module_name(path: Path) -> str:
    rel = path.relative_to(BACKEND_ROOT)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    mapping: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            mapping[child] = parent
    return mapping


def _in_function(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    cur: ast.AST | None = node
    while cur in parents:
        parent = parents[cur]
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return True
        cur = parent
    return False


def _under_type_checking(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    cur: ast.AST | None = node
    while cur in parents:
        parent = parents[cur]
        if isinstance(parent, ast.If):
            test = parent.test
            if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
                return True
            if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
                return True
        cur = parent
    return False


def _allowlisted(module: str, node: ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Import):
        return any((module, alias.name.split(".", 1)[0]) in INLINE_IMPORT_ALLOWLIST for alias in node.names) or any(
            (module, alias.name) in INLINE_IMPORT_ALLOWLIST for alias in node.names
        )
    if node.module and (module, node.module) in INLINE_IMPORT_ALLOWLIST:
        return True
    if node.module and (module, node.module.split(".", 1)[0]) in INLINE_IMPORT_ALLOWLIST:
        return True
    return False


@pytest.mark.parametrize("path", _iter_prod_py_files(), ids=_module_name)
def test_no_inline_imports(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    parents = _parents(tree)
    module = _module_name(path)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if not _in_function(node, parents):
            continue
        if _under_type_checking(node, parents):
            continue
        if _allowlisted(module, node):
            continue
        offenders.append(f"L{node.lineno}: {ast.unparse(node)}")
    if offenders:
        raise AssertionError(
            f"{module} has function-body imports (hoist to module top; "
            f"see backend-layout Import placement):\n  " + "\n  ".join(offenders)
        )
