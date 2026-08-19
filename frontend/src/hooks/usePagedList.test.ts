import { describe, expect, it } from "vitest";

import { shouldApplyPagedListResult } from "@/hooks/usePagedList";

describe("shouldApplyPagedListResult", () => {
  it("applies only the latest in-flight generation", () => {
    expect(shouldApplyPagedListResult(1, 1)).toBe(true);
    expect(shouldApplyPagedListResult(1, 2)).toBe(false);
    expect(shouldApplyPagedListResult(2, 2)).toBe(true);
  });
});
