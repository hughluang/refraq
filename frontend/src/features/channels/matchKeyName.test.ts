import { describe, expect, it } from "vitest";

import { resolvedMatchKeyName } from "@/features/channels/matchKeyName";

const attributes = [
  { name: "sku", business_key: true },
  { name: "name", business_key: false },
];

describe("resolvedMatchKeyName", () => {
  it("uses the business key when the match key is empty", () => {
    expect(resolvedMatchKeyName(null, attributes)).toBe("sku");
    expect(resolvedMatchKeyName("", attributes)).toBe("sku");
  });

  it("returns null when the head has no business key", () => {
    expect(resolvedMatchKeyName(null, [{ name: "name", business_key: false }])).toBeNull();
  });

  it("uses a named match key that exists on the head", () => {
    expect(resolvedMatchKeyName("name", attributes)).toBe("name");
  });

  it("returns null when the named match key is not on the head", () => {
    expect(resolvedMatchKeyName("row_id", attributes)).toBeNull();
    expect(resolvedMatchKeyName(1, attributes)).toBeNull();
  });
});
