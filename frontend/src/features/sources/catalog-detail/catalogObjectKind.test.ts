import { describe, expect, it } from "vitest";

import { isSampleEligible } from "@/features/sources/catalog-detail/catalogObjectKind";

describe("isSampleEligible", () => {
  it("hides Sample for routines", () => {
    expect(isSampleEligible("table")).toBe(true);
    expect(isSampleEligible("view")).toBe(true);
    expect(isSampleEligible("materialized_view")).toBe(true);
    expect(isSampleEligible("procedure")).toBe(false);
    expect(isSampleEligible("function")).toBe(false);
  });
});
