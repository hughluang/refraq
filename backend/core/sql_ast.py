"""SQL AST primitives shared by product domains.

Parse and walk helpers only. Each domain owns its allow and deny policy.
"""

from __future__ import annotations

from sqlglot import exp

# Read-only query roots the Source guard already allows.
READ_QUERY_ROOTS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)

# Write and DDL nodes the Source guard already rejects anywhere in the tree.
# Commit and Rollback are not Transaction subclasses; callers that must reject
# them name those types themselves.
WRITE_OR_DDL: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Merge,
    exp.Copy,
    exp.Command,
    exp.Transaction,
    exp.Lock,
)


def iter_function_names(statement: exp.Expression) -> set[str]:
    """Function names visible to the Source guard.

    Anonymous calls contribute ``this``. Other calls contribute an identifier
    or string ``this`` only. A typed call whose ``this`` is empty is absent;
    that is the Source guard's historical walk, kept so its deny set does not
    grow by a class rename.
    """
    names: set[str] = set()
    for node in statement.walk():
        if isinstance(node, exp.Anonymous):
            names.add(str(node.this).lower())
            continue
        if isinstance(node, exp.Func):
            fn = node.this
            if isinstance(fn, exp.Identifier):
                names.add(str(fn.this).lower())
            elif isinstance(fn, str):
                names.add(fn.lower())
    return names
