import { describe, expect, it } from "vitest";

import {
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
