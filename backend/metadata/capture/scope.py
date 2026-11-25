"""Pure capture authority and published-scope helpers shared by every engine profile.

This module has no persistence or runtime imports so engine adapters and the
management layer can both depend on it without import cycles.
"""

AUTHORITY_KEYS = (
    "source_id",
    "binding_id",
    "owner_epoch",
    "runtime_instance_id",
    "capture_generation",
    "control_revision",
    "credential_revision",
)


def included_tables(published_scope):
    return [table for table in published_scope if table["included"]]


def selected_tables(profile_scope, published_scope):
    qualified = set(profile_scope.get("tables", []))
    return [entry for entry in included_tables(published_scope) if entry["qualified_table"] in qualified]


def profile_matches_scope(profile_scope, published_scope):
    return bool(selected_tables(profile_scope, published_scope))
