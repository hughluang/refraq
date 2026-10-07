import { describe, expect, it } from "vitest";

import {
  classifyAccessProblem,
  columnsFromMatrix,
  appendEditorCondition,
  isMaskedPresentation,
  literalOperand,
  matrixColumn,
  narrowBody,
  presentCell,
  serializeRule,
  validateLadder,
  viewsStatusKey,
  withheldNames,
  type RuleLeaf,
  type RuleNode,} from "@/features/entities/accessLogic";

describe("validateLadder", () => {
  it("requires clear first and unique keys", () => {
    expect(validateLadder([{ key: "clear", mode: "clear" }])).toBeNull();
    expect(
      validateLadder([
        { key: "clear", mode: "clear" },
        { key: "last4", mode: { type: "partial", keep_first: 0, keep_last: 4 } },
      ]),
    ).toBeNull();
    expect(validateLadder([])).toBe("empty");
    expect(validateLadder([{ key: "last4", mode: { type: "null" } }])).toBe("first");
    expect(
      validateLadder([
        { key: "clear", mode: "clear" },
        { key: "clear", mode: { type: "null" } },
      ]),
    ).toBe("duplicate");
  });
});

describe("profile matrix", () => {
  it("reads a blank cell as absent and writes only chosen levels", () => {
    expect(
      matrixColumn("att_note", [{ attribute_id: "att_sku", level: "clear" }]),
    ).toBe("");
    expect(matrixColumn("att_sku", [{ attribute_id: "att_sku", level: "last4" }])).toBe(
      "last4",
    );
    expect(
      columnsFromMatrix(["att_sku", "att_note"], { att_sku: "clear", att_note: "" }),
    ).toEqual([{ attribute_id: "att_sku", level: "clear" }]);
  });
});

describe("row rule editor", () => {
  const leaf = (value: string): RuleLeaf => ({
    kind: "leaf",
    op: "eq",
    attributeId: "att_region",
    operand: { kind: "value", value },
  });

  it("saves a flat AND of leaves and nothing for an empty editor", () => {
    const empty: RuleNode = { kind: "and", children: [] };
    expect(serializeRule(empty)).toBeNull();
    const saved = appendEditorCondition(
      appendEditorCondition(empty, leaf("EAST")),
      {
        kind: "leaf",
        op: "is_null",
        attributeId: "att_sku",
        operand: { kind: "subject_attr", key: "region" },
      },
    );
    expect(serializeRule(saved)).toEqual({
      and: [
        { eq: { attr: "att_region", value: "EAST" } },
        { is_null: { attr: "att_sku", subject_attr: "region" } },
      ],
    });
  });
});

describe("views status", () => {
  it("does not call a missing serving table ready", () => {
    expect(
      viewsStatusKey({ head_version_id: null, views: { state: "ready" } }),
    ).toBe("entities.access.views.noHead");
    expect(
      viewsStatusKey({ head_version_id: "ver_1", views: { state: "ready" } }),
    ).toBe("entities.access.views.ready");
    expect(
      viewsStatusKey({ head_version_id: "ver_1", views: { state: "pending" } }),
    ).toBe("entities.access.views.pending");
  });
});

describe("access problems", () => {
  it("names pending and the cap", () => {
    expect(classifyAccessProblem("ENTITY_ACCESS_PENDING")).toBe("pending");
    expect(classifyAccessProblem("ENTITY_ACCESS_COMBINATION_LIMIT")).toBe(
      "combination_limit",
    );
    expect(classifyAccessProblem("ENTITY_NOT_FOUND")).toBe("other");
  });
});

describe("narrowing", () => {
  it("omits the field when unset and never sends an extra identity", () => {
    expect(narrowBody("none", "")).toEqual({});
    expect(narrowBody("user", "ignored")).toEqual({ narrow: { type: "user" } });
    expect(narrowBody("role", "role_1")).toEqual({
      narrow: { type: "role", id: "role_1" },
    });
  });
});

describe("presentCell", () => {
  it("shows withheld as inaccessible and null as empty", () => {
    expect(
      presentCell({
        name: "note",
        value: null,
        withheld: ["note"],
        referenceHidden: false,
      }).kind,
    ).toBe("withheld");
    expect(
      presentCell({
        name: "note",
        value: null,
        withheld: [],
        referenceHidden: false,
      }).kind,
    ).toBe("empty");
  });

  it("hides an invisible reference target and reads mask presentation", () => {
    const masked = presentCell({
      name: "phone",
      value: "138****",
      withheld: [],
      referenceHidden: false,
    });
    expect(masked.kind).toBe("value");
    expect(isMaskedPresentation([{ mode: "clear" }, { mode: { type: "partial" } }])).toBe(
      true,
    );
    expect(
      presentCell({
        name: "supplier",
        value: "sup_1",
        withheld: null,
        referenceHidden: true,
      }).kind,
    ).toBe("inaccessible_record");
  });

  it("splits an in-list and treats is_null as a boolean", () => {
    expect(literalOperand("in", "a, b")).toEqual(["a", "b"]);
    expect(literalOperand("is_null", "true")).toBe(true);
    expect(literalOperand("eq", "west")).toBe("west");
  });

  it("reads the withheld marker field", () => {
    expect(withheldNames({ __withheld: ["note", 1] }, "__withheld")).toEqual(["note"]);
    expect(withheldNames({ sku: "A" }, null)).toEqual([]);
  });
});
