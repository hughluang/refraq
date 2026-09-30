import { describe, expect, it } from "vitest";

import { EMPTY_ATTRIBUTE } from "@/features/entities/constants";
import {
  attributesFromDrafts,
  draftsFromVersion,
  isLegalTableName,
  referenceSummaryLabel,
} from "@/features/entities/entityPresentation";
import type { AttributeDraft, EntityVersion } from "@/features/entities/types";

function draft(overrides: Partial<AttributeDraft> = {}): AttributeDraft {
  return { ...EMPTY_ATTRIBUTE, ...overrides };
}

describe("attributesFromDrafts", () => {
  it("persists an empty shape", () => {
    expect(attributesFromDrafts([])).toEqual([]);
  });

  it("keeps named string drafts and trims fields", () => {
    expect(
      attributesFromDrafts([
        draft({
          name: " sku ",
          max_length: "32",
          required: false,
          unique: true,
          indexed: true,
          description: " SKU code ",
        }),
      ]),
    ).toEqual([
      {
        type: "string",
        name: "sku",
        required: false,
        unique: true,
        indexed: true,
        description: "SKU code",
        config: { max_length: 32 },
      },
    ]);
  });

  it("maps reference and text without extra config", () => {
    expect(
      attributesFromDrafts([
        draft({
          type: "reference",
          name: "supplier_id",
          target_entity_id: " ent_supplier ",
          target_name: "Supplier",
          target_table_name: "supplier",
        }),
        draft({ type: "text", name: "notes" }),
      ]),
    ).toEqual([
      {
        type: "reference",
        name: "supplier_id",
        required: false,
        unique: false,
        indexed: false,
        description: null,
        config: { target_entity_id: "ent_supplier" },
      },
      {
        type: "text",
        name: "notes",
        required: false,
        unique: false,
        indexed: false,
        description: null,
        config: {},
      },
    ]);
  });

  it("maps decimal precision and enumeration lines", () => {
    expect(
      attributesFromDrafts([
        draft({
          name: "amount",
          type: "decimal",
          precision: "10",
          scale: "2",
        }),
        draft({
          name: "status",
          type: "dictionary",
          dictionary_id: "cl_status",
        }),
      ]),
    ).toEqual([
      {
        type: "decimal",
        name: "amount",
        required: false,
        unique: false,
        indexed: false,
        description: null,
        config: { precision: 10, scale: 2 },
      },
      {
        type: "dictionary",
        name: "status",
        required: false,
        unique: false,
        indexed: false,
        description: null,
        config: { dictionary_id: "cl_status" },
      },
    ]);
  });
});

describe("draftsFromVersion", () => {
  it("maps an empty version shape to no drafts", () => {
    expect(draftsFromVersion({ attributes: [] } as EntityVersion)).toEqual([]);
  });

  it("keeps reference config when other config fields are omitted", () => {
    expect(
      draftsFromVersion({
        attributes: [
          {
            type: "reference",
            name: "supplier_id",
            required: false,
            unique: false,
            indexed: false,
            description: null,
            config: { target_entity_id: "ent_supplier" },
            target: {
              entity_id: "ent_supplier",
              name: "Supplier",
              table_name: "supplier",
            },
          },
        ],
      } as EntityVersion),
    ).toEqual([
      {
        ...EMPTY_ATTRIBUTE,
        type: "reference",
        name: "supplier_id",
        target_entity_id: "ent_supplier",
        target_name: "Supplier",
        target_table_name: "supplier",
      },
    ]);
  });

  it("keeps the linked code list summary on the draft", () => {
    const [drafted] = draftsFromVersion({
      attributes: [
        {
          type: "dictionary",
          name: "status",
          required: false,
          unique: false,
          indexed: false,
          description: null,
          config: { dictionary_id: "cl_status" },
          dictionary: {
            id: "cl_status",
            name: "order_status",
            display_name: "Order status",
            deprecated: false,
          },
          behind: true,
        },
      ],
    } as EntityVersion);
    expect(drafted.dictionary_id).toBe("cl_status");
    expect(drafted.dictionary_display_name).toBe("Order status");
    expect(drafted.behind).toBe(true);
    expect(attributesFromDrafts([drafted])).toEqual([
      {
        type: "dictionary",
        name: "status",
        required: false,
        unique: false,
        indexed: false,
        description: null,
        config: { dictionary_id: "cl_status" },
      },
    ]);
  });

  it("labels a reference from the entity, the form, or the raw id", () => {
    expect(
      referenceSummaryLabel({
        targetEntityId: "ent_supplier",
        selfEntityId: null,
        selfName: "",
        selfTableName: "",
        cachedName: "Supplier",
        cachedTableName: "supplier",
        emptyNameLabel: "This entity",
      }),
    ).toBe("Supplier（supplier）");
    expect(
      referenceSummaryLabel({
        targetEntityId: "self",
        selfEntityId: null,
        selfName: "",
        selfTableName: "items",
        cachedName: "",
        cachedTableName: "",
        emptyNameLabel: "This entity",
      }),
    ).toBe("This entity（items）");
    expect(
      referenceSummaryLabel({
        targetEntityId: "ent_gone",
        selfEntityId: "ent_items",
        selfName: "Items",
        selfTableName: "items",
        cachedName: "",
        cachedTableName: "",
        emptyNameLabel: "This entity",
      }),
    ).toBe("ent_gone");
  });
});

describe("isLegalTableName", () => {
  it("rejects a physical table name and accepts a business stem", () => {
    expect(isLegalTableName("material")).toBe(true);
    expect(isLegalTableName("encv_0123456789ab")).toBe(true);
    expect(isLegalTableName("material__v1__0123456789abcdef")).toBe(false);
  });
});
