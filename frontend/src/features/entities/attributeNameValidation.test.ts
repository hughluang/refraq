import { describe, expect, it } from "vitest";

import {
  ATTRIBUTE_NAME_MAX_LEN,
  attributeNameError,
} from "@/features/entities/attributeNameValidation";

describe("attributeNameError", () => {
  it("allows empty placeholder rows", () => {
    expect(attributeNameError("", [])).toBeNull();
    expect(attributeNameError("   ", ["sku"])).toBeNull();
  });

  it("accepts a valid name", () => {
    expect(attributeNameError("sku_code", ["sku_code"])).toBeNull();
  });

  it("rejects charset violations", () => {
    expect(attributeNameError("1bad", ["1bad"])).toBe("charset");
    expect(attributeNameError("Bad", ["Bad"])).toBe("charset");
    expect(attributeNameError("sku-code", ["sku-code"])).toBe("charset");
  });

  it("rejects names over the column length limit", () => {
    const tooLong = `a${"x".repeat(ATTRIBUTE_NAME_MAX_LEN)}`;
    expect(attributeNameError(tooLong, [tooLong])).toBe("tooLong");
  });

  it("rejects the reserved platform primary key name", () => {
    expect(attributeNameError("row_id", ["row_id"])).toBe("reserved");
  });

  it("rejects duplicates within the version draft", () => {
    expect(attributeNameError("sku", ["sku", "qty", "sku"])).toBe("duplicate");
  });
});
