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
    "describe_entity": (
        "Describe one Business Entity as the current user can read it. "
        "Returns attributes in that read shape, with types, descriptions, "
        "the business key, presentation levels, may_be_withheld, and "
        "withheld_field. Dictionary attributes include up to 50 codes with "
        "labels and active; codes_truncated is true when more exist. "
        "references lists each reference attribute's target table_name and "
        "target business key, or null when that Entity is not visible. "
        "inbound_references lists visible Entities and attributes that "
        "reference this one. Unknown and unreadable table_name values fail "
        "the same way. Does not accept narrow. Requires entity:data_read. "
        "Join later SQL on these declared references. Next: "
        "list_dictionary_codes when codes_truncated is true."
    ),
    "list_dictionary_codes": (
        "Page the dictionary codes of one attribute on an Entity the current "
        "user can read. Codes are the published head snapshot, with current "
        "labels and active taken from the Dictionary. Each item is code, "
        "label, and active. query_text is an optional case-insensitive "
        "substring of code or label. limit defaults to 50 and is at most 200. "
        "An attribute that is missing, hidden, or not a dictionary is "
        "REQUEST_INVALID. Does not accept narrow. Requires entity:data_read."
    ),
    "get_row": (
        "Read one row of a Business Entity the current user can read. "
        "Pass table_name and exactly one of row_id (an integer >= 1) or "
        "business_key. Returns row, the same object Entity Data API get "
        "returns. Unknown and unreadable table_name values fail the same "
        "way. A missing row is ENTITY_ROW_NOT_FOUND. Does not accept "
        "narrow. Requires entity:data_read."
    ),
    "query_rows": (
        "Query rows of a Business Entity the current user can read. "
        "filters, fields, limit, offset, and include_total follow Entity "
        "Data API query. Omit after_row_id for an offset page of items, "
        "total, limit, and offset. Pass after_row_id, including null, for "
        "a keyset page of items, limit, and next_after_row_id; do not "
        "combine it with offset or include_total. limit defaults to 50 "
        "and must be <= 200. offset must be <= 10000. Out-of-range limits "
        "are REQUEST_INVALID and are not clamped. Unknown and unreadable "
        "table_name values fail the same way. Does not accept narrow. "
        "Requires entity:data_read."
    ),
    "validate_sql": (
        "Check one read-only SQL statement that names Business Entities by "
        "table_name. Returns entities, the referenced table_name values sorted, "
        "and partial_columns, the row-varying columns the statement names. "
        "Does not execute the statement and writes no Entity Access Log record. "
        "An unknown table_name and a table_name without an effective read grant "
        "fail with the same error. Requires entity:data_read. Next: run_sql."
    ),
}
