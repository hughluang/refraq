"""Author code is the body of ``def main(self)``. Compilation does not execute it.

Attribute and subscript loads are rewritten into step calls so a JSON null is
Python ``None`` and the next step still fails with that step's name.
"""

from __future__ import annotations

import ast
from types import CodeType

CODE_MAX_BYTES = 64 * 1024

STEP_ATTR = "_step_attr"
STEP_SUB = "_step_sub"


def function_source(source: str) -> str:
    """Indent ``source`` as the body of ``def main(self)``."""
    lines = source.splitlines()
    if not lines:
        lines = [""]
    body = "\n".join("" if not line.strip() else f"    {line}" for line in lines)
    return f"def main(self):\n{body}\n"


def author_line(lineno: int | None) -> int:
    """Map a line in the wrapped function back to the author's source."""
    if lineno is None or lineno <= 1:
        return 1
    return lineno - 1


def compile_expression(expression: str) -> CodeType:
    """Compile one author expression, rewriting attribute and subscript loads."""
    tree = ast.parse(expression, filename="<expression>", mode="eval")
    rewritten = _StepRewriter().visit(tree)
    ast.fix_missing_locations(rewritten)
    return compile(rewritten, "<expression>", "eval")


def compile_author_code(source: str) -> CodeType:
    """Compile author code as ``main``, rewriting attribute and subscript loads."""
    tree = ast.parse(function_source(source), filename="<code>", mode="exec")
    rewritten = _StepRewriter().visit(tree)
    ast.fix_missing_locations(rewritten)
    return compile(rewritten, "<code>", "exec")


class _StepRewriter(ast.NodeTransformer):
    """Replace load-context attribute and subscript with a step call.

    Store and delete keep Python's own syntax so assignment still writes.
    """

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        if not isinstance(node.ctx, ast.Load):
            return self.generic_visit(node)
        value = self.visit(node.value)
        call = ast.Call(
            func=ast.Name(id=STEP_ATTR, ctx=ast.Load()),
            args=[value, ast.Constant(node.attr)],
            keywords=[],
        )
        return ast.copy_location(call, node)

    def visit_Subscript(self, node: ast.Subscript) -> ast.AST:
        if not isinstance(node.ctx, ast.Load):
            return self.generic_visit(node)
        value = self.visit(node.value)
        call = ast.Call(
            func=ast.Name(id=STEP_SUB, ctx=ast.Load()),
            args=[value, self._key_expr(node.slice)],
            keywords=[],
        )
        return ast.copy_location(call, node)

    def _key_expr(self, node: ast.AST) -> ast.expr:
        if isinstance(node, ast.Slice):
            return self._slice_call(node)
        if isinstance(node, ast.Tuple):
            copied = ast.Tuple(elts=[self._key_expr(elt) for elt in node.elts], ctx=ast.Load())
            return ast.copy_location(copied, node)
        return self.visit(node)

    def _slice_call(self, node: ast.Slice) -> ast.Call:
        def bound(part: ast.expr | None) -> ast.expr:
            if part is None:
                return ast.Constant(None)
            return self.visit(part)

        call = ast.Call(
            func=ast.Name(id="slice", ctx=ast.Load()),
            args=[bound(node.lower), bound(node.upper), bound(node.step)],
            keywords=[],
        )
        return ast.copy_location(call, node)
