import { describe, expect, it } from "vitest";

import type { CatalogColumn } from "@/features/sources/types";
import {
  batchItemsFromDirty,
  dirtyColumnIds,
  draftFromColumn,
  draftsEqual,
  draftsFromColumns,
  filterColumns,
  foreignKeyNames,
  normalizeForSave,
  primaryKeyNames,
  shouldReplaceColumnDrafts,
} from "@/features/sources/catalog-detail/columnDrafts";

function col(
  patch: Partial<CatalogColumn> & Pick<CatalogColumn, "id" | "name">,
): CatalogColumn {
  return {
    locator_key: `col/${patch.name}`,
    data_type: "text",
    nullable: true,
    business_name: null,
    business_description: null,
    ordinal: 1,
    is_present: true,
    ...patch,
  };
}

describe("draftFromColumn / normalizeForSave", () => {
  it("round-trips empty semantics to null", () => {
    const draft = draftFromColumn(col({ id: "1", name: "status" }));
    expect(draft.column_semantics).toEqual({
      semantic_type: "",
      value_pattern: "",
      unit: "",
    });
    expect(normalizeForSave(draft).column_semantics).toBeNull();
  });

  it("keeps trimmed semantics and drops blank enum codes", () => {
    const draft = draftFromColumn(
      col({
        id: "1",
        name: "status",
        column_semantics: { semantic_type: " code ", unit: "" },
        enum_catalog: [
          { code: " a ", label: "", description: " d " },
          { code: "  ", label: "x", description: null },
        ],
      }),
    );
    expect(normalizeForSave(draft)).toEqual({
      business_name: "",
      business_description: "",
      column_semantics: {
        semantic_type: "code",
        value_pattern: null,
        unit: null,
      },
      enum_catalog: [{ code: "a", label: "a", description: "d" }],
    });
  });
});

describe("draftsEqual / dirtyColumnIds / batchItemsFromDirty", () => {
  it("detects dirty drafts and builds batch items", () => {
    const columns = [
      col({ id: "a", name: "id", business_name: "ID" }),
      col({ id: "b", name: "name" }),
    ];
    const baseline = draftsFromColumns(columns);
    const drafts = {
      ...baseline,
      a: { ...baseline.a, business_name: "Identifier" },
    };
    expect(draftsEqual(baseline.a, drafts.a)).toBe(false);
    const dirty = dirtyColumnIds(columns, drafts, baseline);
    expect(dirty).toEqual(["a"]);
    expect(batchItemsFromDirty(columns, drafts, dirty)[0]).toMatchObject({
      column_name: "id",
      business_name: "Identifier",
    });
  });
});

describe("filterColumns", () => {
  const columns = [
    col({ id: "1", name: "id", business_name: "ID" }),
    col({
      id: "2",
      name: "status",
      business_name: "Status",
      business_description: "order status",
      enum_catalog: [{ code: "open", label: "Open" }],
    }),
    col({ id: "3", name: "gone", is_present: false }),
  ];
  const drafts = draftsFromColumns(columns);
  const pkNames = primaryKeyNames(["id"]);
  const fkNames = foreignKeyNames([{ columns: ["status"] }]);

  it("filters by search and structural flags", () => {
    expect(
      filterColumns(columns, drafts, {
        query: "stat",
        filter: "all",
        pkNames,
        fkNames,
      }).map((c) => c.id),
    ).toEqual(["2"]);
    expect(
      filterColumns(columns, drafts, {
        query: "",
        filter: "pk",
        pkNames,
        fkNames,
      }).map((c) => c.name),
    ).toEqual(["id"]);
    expect(
      filterColumns(columns, drafts, {
        query: "",
        filter: "fk",
        pkNames,
        fkNames,
      }).map((c) => c.name),
    ).toEqual(["status"]);
    expect(
      filterColumns(columns, drafts, {
        query: "",
        filter: "absent",
        pkNames,
        fkNames,
      }).map((c) => c.name),
    ).toEqual(["gone"]);
    expect(
      filterColumns(columns, drafts, {
        query: "",
        filter: "enum",
        pkNames,
        fkNames,
      }).map((c) => c.name),
    ).toEqual(["status"]);
    expect(
      filterColumns(columns, drafts, {
        query: "",
        filter: "filled",
        pkNames,
        fkNames,
      }).map((c) => c.name),
    ).toEqual(["status"]);
    expect(
      filterColumns(columns, drafts, {
        query: "",
        filter: "empty",
        pkNames,
        fkNames,
      }).map((c) => c.name),
    ).toEqual(["id", "gone"]);
  });
});

describe("shouldReplaceColumnDrafts", () => {
  it("replaces on first mount, object identity change, and refresh epoch", () => {
    expect(
      shouldReplaceColumnDrafts({
        objectId: "obj_a",
        previousObjectId: undefined,
        reloadEpoch: 0,
        previousReloadEpoch: undefined,
      }),
    ).toBe(true);
    expect(
      shouldReplaceColumnDrafts({
        objectId: "obj_a",
        previousObjectId: "obj_a",
        reloadEpoch: 0,
        previousReloadEpoch: 0,
      }),
    ).toBe(false);
    expect(
      shouldReplaceColumnDrafts({
        objectId: "obj_b",
        previousObjectId: "obj_a",
        reloadEpoch: 0,
        previousReloadEpoch: 0,
      }),
    ).toBe(true);
    expect(
      shouldReplaceColumnDrafts({
        objectId: "obj_a",
        previousObjectId: "obj_a",
        reloadEpoch: 1,
        previousReloadEpoch: 0,
      }),
    ).toBe(true);
  });
});
