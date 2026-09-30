import { describe, expect, it } from "vitest";

import { EMPTY_ATTRIBUTE } from "@/features/entities/constants";
import {
  attributeConfigSummary,
  attributeDraftIssues,
  firstAttributeErrorIndex,
} from "@/features/entities/attributeDraftValidation";
import type { AttributeDraft } from "@/features/entities/types";

function draft(overrides: Partial<AttributeDraft> = {}): AttributeDraft {
  return { ...EMPTY_ATTRIBUTE, ...overrides };
}

function fields(item: AttributeDraft, names: readonly string[]) {
  return attributeDraftIssues(item, names).map((issue) => issue.field);
}

describe("attributeDraftIssues", () => {
  it("requires a legal name and a string length in range", () => {
    expect(fields(draft({ name: "" }), [""])).toEqual(["name", "max_length"]);
    expect(fields(draft({ name: "sku", max_length: "" }), ["sku"])).toEqual([
      "max_length",
    ]);
    expect(fields(draft({ name: "sku", max_length: "0" }), ["sku"])).toEqual([
      "max_length",
    ]);
    expect(
      fields(draft({ name: "sku", max_length: "65536" }), ["sku"]),
    ).toEqual(["max_length"]);
    expect(fields(draft({ name: "sku", max_length: "32" }), ["sku"])).toEqual(
      [],
    );
  });

  it("requires decimal precision and a scale within that precision", () => {
    expect(
      fields(draft({ name: "amount", type: "decimal" }), ["amount"]),
    ).toEqual(["precision", "scale"]);
    expect(
      fields(
        draft({
          name: "amount",
          type: "decimal",
          precision: "10",
          scale: "12",
        }),
        ["amount"],
      ),
    ).toEqual(["scale"]);
    expect(
      fields(
        draft({
          name: "amount",
          type: "decimal",
          precision: "10",
          scale: "2",
        }),
        ["amount"],
      ),
    ).toEqual([]);
  });

  it("requires a code list on an enumeration attribute", () => {
    expect(
      fields(draft({ name: "status", type: "dictionary" }), ["status"]),
    ).toEqual(["dictionary_id"]);
    expect(
      fields(
        draft({
          name: "status",
          type: "dictionary",
          dictionary_id: "cl_status",
        }),
        ["status"],
      ),
    ).toEqual([]);
  });

  it("requires a reference target and ignores config on plain types", () => {
    expect(
      fields(draft({ name: "supplier_id", type: "reference" }), ["supplier_id"]),
    ).toEqual(["target_entity_id"]);
    expect(
      fields(draft({ name: "notes", type: "text", max_length: "" }), ["notes"]),
    ).toEqual([]);
  });
});

describe("attributeConfigSummary", () => {
  it("returns type configuration and skips the rest", () => {
    expect(attributeConfigSummary(draft({ max_length: "64" }))).toEqual({
      kind: "max_length",
      value: "64",
    });
    expect(
      attributeConfigSummary(
        draft({ type: "decimal", precision: "10", scale: "2" }),
      ),
    ).toEqual({ kind: "decimal", precision: "10", scale: "2" });
    expect(
      attributeConfigSummary(
        draft({
          type: "dictionary",
          dictionary_id: "cl_status",
          dictionary_display_name: "Order status",
          behind: true,
        }),
      ),
    ).toEqual({
      kind: "dictionary",
      label: "Order status",
    });
    expect(
      attributeConfigSummary(
        draft({ type: "reference", target_entity_id: "ent_supplier" }),
      ),
    ).toBeNull();
    expect(attributeConfigSummary(draft({ type: "text" }))).toBeNull();
    expect(attributeConfigSummary(draft({ max_length: "" }))).toBeNull();
  });
});

describe("firstAttributeErrorIndex", () => {
  it("returns the lowest attribute index that has an error", () => {
    expect(
      firstAttributeErrorIndex({
        name: "Required",
        "attributes.2.max_length": "Required",
        "attributes.0.name": "Required",
      }),
    ).toBe(0);
    expect(firstAttributeErrorIndex({ name: "Required" })).toBeNull();
  });
});
