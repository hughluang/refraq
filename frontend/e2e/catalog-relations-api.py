#!/usr/bin/env python3
"""Seed the real memory API for the focused Relations browser suite.

Use as E2E_PYTHON; all HTTP handlers and authorization remain the production app.
Catalog objects have no public create endpoint, so only initial collection is seeded.
"""

import os
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.time import utc_now
from backend.metadata.catalog.records import (
    CatalogColumnRecord,
    CatalogForeignKeyRecord,
    CatalogObjectRecord,
)
from backend.metadata.catalog.structure_refresh import apply_structure_snapshot
from backend.metadata.sources.store import SourceRecord, get_source_store


def seed() -> None:
    if os.environ.get("REFRAQ_STORE_BACKEND") != "memory":
        raise RuntimeError("Relations fixtures require the memory backend")
    now = utc_now()
    for case in ("author", "edit", "lifecycle", "failure", "paths", "dense", "en-light", "en-dark", "zh-light", "zh-dark"):
        key = f"relations-{case}"
        source = SourceRecord(
            id=f"src_{key}", key=key, locator_key=f"src/postgresql/{key}",
            name=key, kind="database", status="active", description=None,
            engine="postgresql", access_ciphertext=None, access_updated_at=None,
            created_at=now, updated_at=now,
        )
        get_source_store().create_source(source)
        objects = []
        names = ("orders", "customer_accounts_with_a_deliberately_long_catalog_object_name")
        if case == "dense":
            names += tuple(f"remote_{index}_with_a_deliberately_long_catalog_object_name" for index in range(3))
        for name in names:
            oid = f"{key}-{name}"
            locator = f"obj/postgresql/{key}/public/table/{name}"
            columns = [CatalogColumnRecord(
                id=f"{oid}-{column}", object_id=oid,
                locator_key=f"col/postgresql/{key}/public/table/{name}/column/{column}",
                name=column, ordinal=index, data_type="integer", nullable=False,
                is_present=True, default_value=None, comment=None, business_name=None,
                business_description=None, column_semantics=None, enum_catalog=None,
                semantic_source=None, field_kind="column", created_at=now, updated_at=now,
            ) for index, column in enumerate(("id", "alternate_id", "foreign_id"))]
            objects.append(CatalogObjectRecord(
                id=oid, source_id=source.id, locator_key=locator, object_type="table",
                schema_name="public", name=name, ddl=None, comment=None, primary_key=["id"],
                is_present=True, business_name=None, business_description=None,
                object_category=None, grain_description=None, business_primary_key=None,
                evidence_summary=None, open_questions=None, semantic_source=None,
                business_semantics_ready=False, semantics_updated_at=None,
                last_structure_job_id=None, collected_at=now, created_at=now,
                updated_at=now, columns=columns,
                foreign_keys=[CatalogForeignKeyRecord(
                    name="orders_customer_fk", columns=["foreign_id"], ref_schema="public",
                    ref_table="customer_accounts_with_a_deliberately_long_catalog_object_name",
                    ref_columns=["id"],
                )] if name == "orders" else [],
            ))
        apply_structure_snapshot(source=source, job_id=f"job_{key}", collected=objects, schema_scope=None)


if __name__ == "__main__":
    # The existing Playwright config passes: <E2E_PYTHON> -m uvicorn backend.main:app ...
    if sys.argv[1:3] != ["-m", "uvicorn"]:
        raise RuntimeError("Expected the existing Playwright uvicorn command")
    seed()
    sys.argv = ["uvicorn", *sys.argv[3:]]
    runpy.run_module("uvicorn", run_name="__main__")
