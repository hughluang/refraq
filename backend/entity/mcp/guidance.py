"""English Entity MCP server instructions and tool descriptions."""

from __future__ import annotations

SERVER_INSTRUCTIONS = """\
Refraq Entity MCP is the read-only face for Business Entity data the current user can read.

Workflow: call list_entities to discover Entities, describe_entity to see the attributes you can use, validate_sql to check a statement, then run_sql to execute it.

Join Entities on the declared references returned by describe_entity. Do not guess join keys from column names.

Masked columns group and filter on masked values, not on the underlying values.

Withheld cells are NULL and are listed in __withheld.

This face does not write Entity data, change definitions, or read the Change Log.
"""

TOOL_DESCRIPTIONS: dict[str, str] = {
    "list_entities": (
        "Page the Business Entities the current user can read that are serving. "
        "Each item has table_name, name, description, and tags. "
        "query_text is an optional case-insensitive substring of name, table_name, "
        "or description. limit defaults to 50 and is at most 200. "
        "Entities without an effective read grant are omitted. "
        "Requires entity:data_read. Next: describe_entity, and join later SQL "
        "on the references that tool declares."
    ),
}
