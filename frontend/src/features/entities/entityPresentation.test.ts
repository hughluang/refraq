import { describe, expect, it } from "vitest";

import { EMPTY_ATTRIBUTE } from "@/features/entities/constants";
import {
  attributesFromDrafts,
  draftsFromVersion,
} from "@/features/entities/entityPresentation";
import type { AttributeDraft, EntityVersion } from "@/features/entities/types";

function draft(
  overrides: Partial<AttributeDraft> = {},
): AttributeDraft {
  return { ...EMPTY_ATTRIBUTE, ...overrides };
}

describe("attributesFromDrafts", () => {
  it("persists an empty shape when no named drafts are present", () => {
    expect(attributesFromDrafts([])).toEqual([]);
    expect(attributesFromDrafts([draft()])).toEqual([]);
    expect(attributesFromDrafts([draft({ name: "   " })])).toEqual([]);
  });

  it("keeps named drafts and trims fields", () => {
    expect(
      attributesFromDrafts([
        draft(),
        draft({
          name: " sku ",
          nullable: true,
          unique: true,
          indexed: true,
          description: " SKU code ",
        }),
      ]),
    ).toEqual([
      {
        name: "sku",
        normalized_type: "string",
        nullable: true,
        unique: true,
        indexed: true,
        description: "SKU code",
      },
    ]);
  });
});

describe("draftsFromVersion", () => {
  it("maps an empty version shape to no drafts", () => {
    expect(
      draftsFromVersion({ attributes: [] } as EntityVersion),
    ).toEqual([]);
  });
});
