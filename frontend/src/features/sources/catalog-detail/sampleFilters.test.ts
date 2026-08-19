import { describe, expect, it } from "vitest";

import {
  buildSampleRequest,
  defaultSampleOrderColumn,
  formatSampleCell,
  isSampleFilterOp,
  isSampleStale,
  isUnstableOrder,
  sampleFilterSnapshot,
} from "@/features/sources/catalog-detail/sampleFilters";

describe("isSampleFilterOp", () => {
  it("accepts known ops only", () => {
    expect(isSampleFilterOp("eq")).toBe(true);
    expect(isSampleFilterOp("contains")).toBe(true);
    expect(isSampleFilterOp("like")).toBe(false);
    expect(isSampleFilterOp("")).toBe(false);
  });
});

describe("sampleFilterSnapshot", () => {
  it("omits value for is_null", () => {
    expect(
      sampleFilterSnapshot({ column: "status", op: "is_null", value: "x" }),
    ).toBe(JSON.stringify({ column: "status", op: "is_null", value: "" }));
  });
});

describe("defaultSampleOrderColumn", () => {
  const col = (name: string, is_present = true) => ({ name, is_present });

  it("prefers primary_key[0] when present", () => {
    expect(
      defaultSampleOrderColumn({
        primary_key: ["id", "tenant"],
        columns: [col("name"), col("id"), col("tenant")],
      }),
    ).toBe("id");
  });

  it("falls back when primary_key[0] is absent", () => {
    expect(
      defaultSampleOrderColumn({
        primary_key: ["gone"],
        columns: [col("a"), col("gone", false)],
      }),
    ).toBe("a");
  });

  it("uses first present column without primary_key", () => {
    expect(
      defaultSampleOrderColumn({
        primary_key: null,
        columns: [col("x", false), col("y")],
      }),
    ).toBe("y");
  });

  it("returns null when no present columns", () => {
    expect(
      defaultSampleOrderColumn({
        primary_key: ["id"],
        columns: [col("id", false)],
      }),
    ).toBeNull();
  });
});

describe("formatSampleCell", () => {
  it("formats nullish as NULL", () => {
    expect(formatSampleCell(null)).toBe("NULL");
    expect(formatSampleCell(undefined)).toBe("NULL");
  });

  it("stringifies objects and arrays as JSON", () => {
    expect(formatSampleCell({ a: 1 })).toBe('{"a":1}');
    expect(formatSampleCell([1, "x"])).toBe('[1,"x"]');
  });

  it("stringifies scalars", () => {
    expect(formatSampleCell(42)).toBe("42");
    expect(formatSampleCell(true)).toBe("true");
    expect(formatSampleCell("hi")).toBe("hi");
  });
});

describe("buildSampleRequest", () => {
  it("omits filters when no column is selected", () => {
    expect(
      buildSampleRequest(
        { column: null, op: "eq", value: "x" },
        null,
        "asc",
        10,
        50,
      ),
    ).toEqual({
      filters: [],
      order_by: [],
      offset: 10,
      limit: 50,
      include_sql: false,
    });
  });

  it("clears is_null value and includes order_by", () => {
    expect(
      buildSampleRequest(
        { column: "status", op: "is_null", value: "x" },
        "id",
        "desc",
        0,
        20,
      ),
    ).toEqual({
      filters: [{ column: "status", op: "is_null", value: "" }],
      order_by: [{ column: "id", direction: "desc" }],
      offset: 0,
      limit: 20,
      include_sql: false,
    });
  });
});

describe("isSampleStale", () => {
  const current = {
    limit: 50,
    offset: 0,
    filterKey: "a",
    orderColumn: "id",
    orderDirection: "asc" as const,
  };

  it("is false when nothing has been applied", () => {
    expect(isSampleStale(null, current)).toBe(false);
  });

  it("is true when applied params differ", () => {
    expect(isSampleStale({ ...current, offset: 50 }, current)).toBe(true);
    expect(isSampleStale(current, current)).toBe(false);
  });
});

describe("isUnstableOrder", () => {
  it("warns when paging without an order column", () => {
    expect(isUnstableOrder(50, null)).toBe(true);
    expect(isUnstableOrder(50, "id")).toBe(false);
    expect(isUnstableOrder(0, null)).toBe(false);
  });
});
