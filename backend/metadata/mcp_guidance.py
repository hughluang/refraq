"""English MCP server instructions, scene prompts, and tool descriptions."""

from __future__ import annotations

SERVER_INSTRUCTIONS = """\
Refraq Metadata MCP is the inquiry and living-registry face for registered Sources, Catalog Objects, admitted semantics, joins, and controlled read-only SQL.

When to connect: if the task might need registry facts, call this MCP without waiting to be asked. Only skip when you can rule out any Source or catalog involvement.

First step: call search_sources with keywords from the task. If no Source matches, say the registry does not cover it, then fall back to local reasoning.

After a Source is in play: prefer a matching prompt (lookup_business, analyze_object, explore_join_path, enrich_semantics). Cite returned business names and descriptions. Prefer cheaper reads (get_object_semantics, get_object_columns, get_object_ddl) unless you need the full get_object payload.

Write-back: when you have checkable understanding and the registry still has gaps, write with set_object_semantics / set_column_semantics. Fill gaps; do not invent; persist open_questions when evidence is weak. Last write wins; read list_semantics_changes if you need the prior values. Time and status meaning live on columns (business_description and optional column_semantics), not as an object-level primary election. Object relationships are join edges with evidence.

Join writes require real SQL/DDL provenance or a run_sql check. Name similarity alone is not evidence. After a verified join, upsert it so later path lookup can use it.

Do not enqueue Jobs or manage Scheduled Tasks on this face.
"""

LOOKUP_BUSINESS_BODY = """\
Goal: judge how far the registry can answer a business question.

Decide from tool results, not from names you already know. Start with search_sources, then search_objects / search_columns. Prefer get_object_semantics before loading columns or DDL.

Deliver: which Sources and objects cover the question, what is still unknown (open_questions), and whether you need find_join_path or run_sql. Do not invent business meaning.
"""

ANALYZE_OBJECT_BODY = """\
Goal: understand one table or view as a source fact (read-only).

Use get_object_semantics, then get_object_columns or get_object_ddl only if needed. get_object is the aggregate when you need everything at once.

Classify object_category only when evidence supports it. Grain is “one row means …”. Time and status meaning belong on the relevant columns. Relationships belong in join edges, not free-text summaries.

Do not write unless the user asked to enrich.
"""

EXPLORE_JOIN_PATH_BODY = """\
Goal: find how objects connect and how a query could walk them.

find_join_path is the join read. Modes: start + query_text (business intent), start + target locator, or start only (graph exploration). Rejected edges are omitted.

If a path is missing but SQL/DDL or run_sql shows a real link, write it with upsert_joins and evidence. Name similarity is not evidence.
"""

ENRICH_SEMANTICS_BODY = """\
Goal: fill admitted object and column semantics and write them back.

Admitted object fields: business_name, business_description, object_category, grain_description, business_primary_key, business_domain_code, evidence_summary, open_questions.
Admitted column fields: business_name, business_description, column_semantics (semantic_type, value_pattern, unit), enum_catalog.

Do not send time_semantics, status_semantics, relation_summary, confidence, or model_routing_hint. Last write wins. MCP cannot clear a field (omit it). Record open_questions when evidence is weak.

After writing, tell the user which fields you left on the object.
"""

TOOL_DESCRIPTIONS: dict[str, str] = {
    "search_sources": (
        "Search or list Sources when you do not yet have a source locator. "
        "query_text matches key, name, engine, or locator; omit it to page. "
        "Read items[].locator_key, then call get_source or list_objects. "
        "Requires sources:read."
    ),
    "get_source": (
        "Read one Source by source_locator_key (projected access, no secrets). "
        "Use after search_sources. Next: list_objects or run_sql. Requires sources:read."
    ),
    "list_objects": (
        "Page Catalog Objects under one Source locator. Optional q is a literal "
        "substring of schema, technical name, or business_name — not Catalog Search. "
        "Items omit columns and DDL. Next: get_object_semantics or get_object. "
        "Requires metadata:read."
    ),
    "get_object": (
        "Aggregate read: object semantics, columns (no normalized_type), and DDL. "
        "Prefer get_object_semantics / get_object_columns / get_object_ddl when you "
        "do not need the full payload. No foreign_keys or indexes. Requires metadata:read."
    ),
    "get_object_semantics": (
        "Object-level admitted semantics only (no columns, no DDL). "
        "Use to scan readiness and open_questions. Requires metadata:read."
    ),
    "get_object_columns": (
        "Columns plus column semantics for one object locator (no DDL). "
        "Use before set_column_semantics. Requires metadata:read."
    ),
    "get_object_ddl": (
        "Stored DDL snapshot (ddl, has_definition). "
        "If has_definition is false, a structure Job has not stored a definition. "
        "Requires metadata:read."
    ),
    "set_object_semantics": (
        "Incremental object semantics write (semantic_source=mcp). "
        "Fill gaps; persist open_questions; do not invent. Last write wins. "
        "MCP cannot clear fields. Requires metadata:write."
    ),
    "set_column_semantics": (
        "Batch column semantics under one object locator. "
        "Each item needs column_name plus at least one field. "
        "Response includes skipped_columns. Requires metadata:write."
    ),
    "list_business_domains": (
        "List Business Domains (code, name). "
        "Use before set_object_semantics.business_domain_code. Requires metadata:read."
    ),
    "create_business_domain": (
        "Create a Business Domain (immutable code, mutable name). "
        "Delete is Console HTTP only. Requires metadata:write."
    ),
    "list_semantics_changes": (
        "Page Semantics Change events for an object locator (old/new values). "
        "Does not restore or lock fields. Requires metadata:read."
    ),
    "search_objects": (
        "Cross-Source Catalog Search for objects. query_text is required. "
        "Same rank as HTTP search (lexical; hybrid when embeddings are configured). "
        "Not the per-Source list. Requires metadata:read."
    ),
    "search_columns": (
        "Cross-Source Catalog Search for columns. query_text is required. "
        "Same rank as HTTP /catalog/columns/search. Requires metadata:read."
    ),
    "list_joins": (
        "List join edges that touch an object locator, including rejected rows. "
        "For paths, use find_join_path. Requires metadata:read."
    ),
    "upsert_join": (
        "Create one join edge (attester mcp). Evidence required. "
        "Duplicate asserted pair is refused; rejected pair is JOIN_REJECTED. "
        "Requires metadata:write."
    ),
    "patch_join": (
        "Amend evidence, kind, or expression. Does not change first attester "
        "or delete eligibility. Requires metadata:write."
    ),
    "reject_join": (
        "Reject a directed pair so no writer (including Jobs) restores it until restore_join. "
        "Use this for automatic edges you must keep out (delete is refused). Requires metadata:write."
    ),
    "restore_join": (
        "Lift Join Rejection. Requires metadata:write."
    ),
    "upsert_joins": (
        "Batch create joins in one Source. Known asserted pairs skipped; "
        "rejected pairs reported, not restored. Evidence required. Requires metadata:write."
    ),
    "delete_join": (
        "Delete a human-created, non-rejected edge. Automatic edges return JOIN_DELETE_AUTOMATIC; "
        "use reject_join instead. Requires metadata:write."
    ),
    "find_join_path": (
        "Join path lookup. Modes: start + query_text (Catalog Search then BFS), "
        "start + target_locator_key, or start only (graph). Rejected edges omitted. "
        "Requires metadata:read."
    ),
    "run_sql": (
        "Single read-only SELECT on a Source locator. Platform AST guards apply. "
        "No Catalog Sample tool; peek here. Requires query:run."
    ),
}
