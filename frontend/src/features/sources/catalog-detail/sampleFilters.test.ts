import { describe, expect, it } from "vitest";

import {
  defaultSampleOrderColumn,
  formatSampleCell,
  isSampleFilterOp,
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
