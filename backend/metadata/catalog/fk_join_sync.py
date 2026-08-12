"""FK/index snapshot merge and FK → Join edge derivation."""

from __future__ import annotations

from dataclasses import replace

from backend.metadata.catalog.records import (
    CatalogForeignKeyRecord,
    CatalogIndexRecord,
    CatalogObjectRecord,
    CatalogWriteAborted,
    new_fk_id,
    new_index_id,
)


def merge_fk_snapshot(
    existing: list[CatalogForeignKeyRecord],
    incoming: list[CatalogForeignKeyRecord],
) -> list[CatalogForeignKeyRecord]:
    by_name = {fk.name: fk for fk in existing}
    seen: set[str] = set()
    out: list[CatalogForeignKeyRecord] = []
    for fk in incoming:
        seen.add(fk.name)
        prev = by_name.get(fk.name)
        if prev is None:
            out.append(
                CatalogForeignKeyRecord(
                    id=new_fk_id(),
                    name=fk.name,
                    columns=list(fk.columns),
                    ref_schema=fk.ref_schema,
                    ref_table=fk.ref_table,
                    ref_columns=list(fk.ref_columns),
                    is_present=True,
                )
            )
        else:
            out.append(
                replace(
                    prev,
                    columns=list(fk.columns),
                    ref_schema=fk.ref_schema,
                    ref_table=fk.ref_table,
                    ref_columns=list(fk.ref_columns),
                    is_present=True,
                )
            )
    for name, prev in by_name.items():
        if name not in seen:
            out.append(replace(prev, is_present=False))
    return out


def merge_index_snapshot(
    existing: list[CatalogIndexRecord],
    incoming: list[CatalogIndexRecord],
) -> list[CatalogIndexRecord]:
    by_name = {idx.name: idx for idx in existing}
    seen: set[str] = set()
    out: list[CatalogIndexRecord] = []
    for idx in incoming:
        seen.add(idx.name)
        prev = by_name.get(idx.name)
        if prev is None:
            out.append(
                CatalogIndexRecord(
                    id=new_index_id(),
                    name=idx.name,
                    columns=list(idx.columns),
                    is_unique=idx.is_unique,
                    is_present=True,
                )
            )
        else:
            out.append(
                replace(
                    prev,
                    columns=list(idx.columns),
                    is_unique=idx.is_unique,
                    is_present=True,
                )
            )
    for name, prev in by_name.items():
        if name not in seen:
            out.append(replace(prev, is_present=False))
    return out


def _present_table_candidates(
    objects: list[CatalogObjectRecord],
    *,
    source_id: str,
    ref_schema: str,
    ref_table: str,
) -> list[CatalogObjectRecord]:
    return [
        o
        for o in objects
        if o.source_id == source_id
        and o.is_present
        and o.schema_name == ref_schema
        and o.name == ref_table
        and o.object_type == "table"
    ]


def _fk_edges_for_object(
    obj: CatalogObjectRecord,
    *,
    present_objects: list[CatalogObjectRecord],
) -> list[tuple[str, str, str, str]]:
    """Resolve present FK edges; each item is (from_id, to_id, evidence, expression)."""
    edges: list[tuple[str, str, str, str]] = []
    col_by_name = {c.name: c for c in obj.columns if c.is_present}
    for fk in obj.foreign_keys:
        if not fk.is_present:
            continue
        if len(fk.columns) != len(fk.ref_columns):
            raise CatalogWriteAborted(
                "JOB_FK_COLUMN_MISMATCH",
                f"FK {fk.name} on {obj.schema_name}.{obj.name} has unequal "
                f"local/ref column counts",
            )
        refs = _present_table_candidates(
            present_objects,
            source_id=obj.source_id,
            ref_schema=fk.ref_schema,
            ref_table=fk.ref_table,
        )
        if not refs:
            raise CatalogWriteAborted(
                "JOB_FK_UNRESOLVED",
                f"FK {fk.name} on {obj.schema_name}.{obj.name} references "
                f"missing table {fk.ref_schema}.{fk.ref_table}",
            )
        if len(refs) > 1:
            raise CatalogWriteAborted(
                "JOB_FK_AMBIGUOUS",
                f"FK {fk.name} on {obj.schema_name}.{obj.name} matches multiple "
                f"tables named {fk.ref_schema}.{fk.ref_table}",
            )
        ref_obj = refs[0]
        ref_cols = {c.name: c for c in ref_obj.columns if c.is_present}
        for from_name, to_name in zip(fk.columns, fk.ref_columns, strict=True):
            from_col = col_by_name.get(from_name)
            to_col = ref_cols.get(to_name)
            if from_col is None or to_col is None:
                raise CatalogWriteAborted(
                    "JOB_FK_UNRESOLVED",
                    f"FK {fk.name} on {obj.schema_name}.{obj.name} cannot resolve "
                    f"columns {from_name}->{to_name}",
                )
            evidence = f"FK {fk.name}"
            expression = f"{from_col.name} = {to_col.name}"
            edges.append((from_col.id, to_col.id, evidence, expression))
    return edges


