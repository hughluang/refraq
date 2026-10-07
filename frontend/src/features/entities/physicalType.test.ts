import { describe, expect, it } from "vitest";

import { EMPTY_ATTRIBUTE } from "@/features/entities/constants";
import { physicalColumnType } from "@/features/entities/physicalType";
import type { AttributeDraft, AttributeType } from "@/features/entities/types";

function draft(overrides: Partial<AttributeDraft> = {}): AttributeDraft {
  return { ...EMPTY_ATTRIBUTE, ...overrides };
}

describe("physicalColumnType", () => {
  it("appends length or precision only when both required numbers are present", () => {
    expect(physicalColumnType(draft({ max_length: "" }))).toBe("VARCHAR");
    expect(physicalColumnType(draft({ max_length: "32" }))).toBe("VARCHAR(32)");
    expect(physicalColumnType(draft({ max_length: "nope" }))).toBe("VARCHAR");
    expect(
      physicalColumnType(draft({ type: "decimal", precision: "", scale: "" })),
    ).toBe("NUMERIC");
    expect(
      physicalColumnType(
        draft({ type: "decimal", precision: "10", scale: "" }),
      ),
    ).toBe("NUMERIC");
    expect(
      physicalColumnType(
        draft({ type: "decimal", precision: "10", scale: "2" }),
      ),
    ).toBe("NUMERIC(10,2)");
    expect(
      physicalColumnType(
        draft({ type: "decimal", precision: "10", scale: "0" }),
      ),
    ).toBe("NUMERIC(10,0)");
  });

  it("renders a frozen reference column from the snapshot", () => {
    expect(
      physicalColumnType(
        draft({
          type: "reference",
          reference_key_type: "string",
          reference_max_length: "16",
        }),
      ),
    ).toBe("VARCHAR(16)");
    expect(
      physicalColumnType(
        draft({ type: "reference", reference_key_type: "integer" }),
      ),
    ).toBe("BIGINT");
    expect(physicalColumnType(draft({ type: "reference" }))).toBe(
      "VARCHAR | BIGINT",
    );
  });

  it("uses the fixed column type for every other attribute type", () => {
    const fixed: Record<Exclude<AttributeType, "string" | "decimal">, string> =
      {
        text: "TEXT",
        integer: "BIGINT",
        number: "DOUBLE PRECISION",
        boolean: "BOOLEAN",
        date: "DATE",
        timestamp: "TIMESTAMPTZ",
        time: "TIME",
        json: "JSONB",
        dictionary: "VARCHAR(64)",
        reference: "VARCHAR | BIGINT",
        user: "VARCHAR(64)",
      };
    for (const [type, column] of Object.entries(fixed)) {
      expect(physicalColumnType(draft({ type: type as AttributeType }))).toBe(
        column,
      );
    }
  });
});
